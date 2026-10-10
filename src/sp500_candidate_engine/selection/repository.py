from __future__ import annotations

import uuid
from datetime import date, datetime

from psycopg.types.json import Jsonb

from sp500_candidate_engine.analytics.db import execute_many
from sp500_candidate_engine.database import _canonical_hash, _stable_uuid
from sp500_candidate_engine.selection.policy import SelectionResult


def selection_run_identity(
    *,
    price_session_date: date,
    scoring_run_id: uuid.UUID,
    policy_version: str,
) -> tuple[uuid.UUID, str]:
    key = _canonical_hash(
        {
            "price_session_date": price_session_date,
            "scoring_run_id": scoring_run_id,
            "policy_version": policy_version,
            "selection_type": "QUANTITATIVE",
        }
    )
    return _stable_uuid("selection-run", key), key


class SelectionRepository:
    def __init__(self, connection: object) -> None:
        self.connection = connection

    def persist(
        self,
        *,
        price_session_date: date,
        cutoff_at: datetime,
        generated_at: datetime,
        valid_until: datetime | None,
        scoring_run_id: uuid.UUID,
        policy_version: str,
        requested_count: int,
        result: SelectionResult,
    ) -> uuid.UUID:
        run_id, key = selection_run_identity(
            price_session_date=price_session_date,
            scoring_run_id=scoring_run_id,
            policy_version=policy_version,
        )
        self.connection.execute(  # type: ignore[attr-defined]
            """
            INSERT INTO selection.selection_run(
                selection_run_id, selection_type, price_session_date,
                cutoff_at, generated_at, valid_until, scoring_run_id,
                policy_version, requested_count, selected_count,
                status, idempotency_key
            )
            VALUES (%s, 'QUANTITATIVE', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (idempotency_key) DO NOTHING
            """,
            (
                run_id,
                price_session_date,
                cutoff_at,
                generated_at,
                valid_until,
                scoring_run_id,
                policy_version,
                requested_count,
                len(result.candidates),
                result.status,
                key,
            ),
        )
        execute_many(
            self.connection,  # type: ignore[arg-type]
            """
            INSERT INTO selection.candidate(
                selection_run_id, instrument_id, position, score,
                rank_overall, score_percentile, rank_sector,
                quality_status, latest_data_at, predicted_return
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'OK', %s, %s)
            ON CONFLICT DO NOTHING
            """,
            [
                (
                    run_id,
                    candidate.instrument_id,
                    candidate.position,
                    candidate.score,
                    candidate.rank_overall,
                    candidate.score_percentile,
                    candidate.rank_sector,
                    cutoff_at,
                    candidate.score,
                )
                for candidate in result.candidates
            ],
        )
        reason_rows = []
        for candidate in result.candidates:
            for priority, reason_code in enumerate(candidate.reason_codes, start=1):
                fingerprint = _canonical_hash(
                    {
                        "selection_run_id": run_id,
                        "instrument_id": candidate.instrument_id,
                        "reason_code": reason_code,
                    }
                )
                reason_rows.append(
                    (
                        _stable_uuid("candidate-reason", fingerprint),
                        run_id,
                        candidate.instrument_id,
                        reason_code,
                        priority,
                        fingerprint,
                        Jsonb(
                            {
                                "score": candidate.score,
                                "rank": candidate.rank_overall,
                            }
                        ),
                    )
                )
        execute_many(
            self.connection,  # type: ignore[arg-type]
            """
            INSERT INTO selection.candidate_reason(
                candidate_reason_id, selection_run_id, instrument_id,
                reason_code, priority, reason_fingerprint, reason_detail
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            reason_rows,
        )
        return run_id
