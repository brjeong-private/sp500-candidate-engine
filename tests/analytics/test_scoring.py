import uuid
from datetime import date

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
