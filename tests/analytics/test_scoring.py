import uuid
from datetime import date

from sp500_candidate_engine.analytics.score_repository import ScoreRepository
from sp500_candidate_engine.analytics.scoring import rank_daily_scores


def test_daily_scores_have_deterministic_rank_and_percentile() -> None:
    first = uuid.UUID("00000000-0000-0000-0000-000000000001")
    second = uuid.UUID("00000000-0000-0000-0000-000000000002")
    scores = rank_daily_scores(
        session_date=date(2026, 10, 8),
        raw_scores={second: 0.5, first: 0.5},
        sectors={first: "Tech", second: "Tech"},
    )

    assert [item.instrument_id for item in scores] == [first, second]
    assert [item.rank_overall for item in scores] == [1, 2]
    assert scores[0].score_percentile == 1.0
    assert scores[1].score_percentile == 0.5


class RecordingConnection:
    def execute(self, _query, parameters):
        self.parameters = parameters


def test_scoring_run_identity_includes_score_semantics() -> None:
    connection = RecordingConnection()
    repository = ScoreRepository(connection)
    arguments = {
        "session_date": date(2026, 10, 8),
        "execution_context_id": uuid.uuid4(),
        "export_run_id": uuid.uuid4(),
        "model_version_id": uuid.uuid4(),
        "universe_version_id": uuid.uuid4(),
        "config_hash": "config",
    }

    short_run = repository.create_run(
        **arguments,
        score_semantics="PREDICTED_5D_RETURN",
    )
    medium_run = repository.create_run(
        **arguments,
        score_semantics="PREDICTED_20D_RETURN",
        prediction_horizon_sessions=20,
    )
    other_horizon = repository.create_run(
        **arguments,
        prediction_horizon_sessions=10,
    )

    assert short_run != medium_run
    assert short_run != other_horizon
