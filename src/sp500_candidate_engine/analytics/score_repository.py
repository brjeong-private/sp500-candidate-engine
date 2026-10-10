from __future__ import annotations

import uuid
from datetime import date

from sp500_candidate_engine.analytics.db import execute_many
from sp500_candidate_engine.analytics.scoring import DailyScore
from sp500_candidate_engine.database import _canonical_hash, _stable_uuid


class ScoreRepository:
    def __init__(self, connection: object) -> None:
        self.connection = connection

    def create_run(
        self,
        *,
        session_date: date,
        execution_context_id: uuid.UUID,
        export_run_id: uuid.UUID,
        model_version_id: uuid.UUID,
        universe_version_id: uuid.UUID,
        config_hash: str,
    ) -> uuid.UUID:
        key = _canonical_hash(
            {
                "session_date": session_date,
                "execution_context_id": execution_context_id,
                "export_run_id": export_run_id,
                "model_version_id": model_version_id,
                "universe_version_id": universe_version_id,
                "config_hash": config_hash,
            }
        )
        run_id = _stable_uuid("scoring-run", key)
        self.connection.execute(  # type: ignore[attr-defined]
            """
            INSERT INTO analytics.scoring_run(
                scoring_run_id, session_date, execution_context_id,
                export_run_id, model_version_id, universe_version_id,
                config_hash, status, idempotency_key
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'RUNNING', %s)
            ON CONFLICT (idempotency_key) DO NOTHING
            """,
            (
                run_id,
                session_date,
                execution_context_id,
                export_run_id,
                model_version_id,
                universe_version_id,
                config_hash,
                key,
            ),
        )
        return run_id

    def write_scores(
        self,
        *,
        scoring_run_id: uuid.UUID,
        scores: tuple[DailyScore, ...],
        prediction_horizon: int,
    ) -> None:
        execute_many(
            self.connection,  # type: ignore[arg-type]
            """
            INSERT INTO analytics.daily_score(
                scoring_run_id, instrument_id, score, rank_overall,
                score_percentile, rank_sector, prediction_horizon, quality_status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (scoring_run_id, instrument_id) DO NOTHING
            """,
            [
                (
                    scoring_run_id,
                    score.instrument_id,
                    score.score,
                    score.rank_overall,
                    score.score_percentile,
                    score.rank_sector,
                    prediction_horizon,
                    score.quality_status,
                )
                for score in scores
            ],
        )
        self.connection.execute(  # type: ignore[attr-defined]
            """
            UPDATE analytics.scoring_run
               SET status = 'SUCCEEDED', computed_at = now()
             WHERE scoring_run_id = %s AND status IN ('RUNNING', 'SUCCEEDED')
            """,
            (scoring_run_id,),
        )
