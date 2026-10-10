from datetime import date

from sp500_candidate_engine.analytics.retraining import should_create_challenger


def test_retraining_waits_for_configured_interval() -> None:
    assert not should_create_challenger(
        last_training_date=date(2026, 10, 1),
        target_date=date(2026, 10, 20),
    )
    assert should_create_challenger(
        last_training_date=date(2026, 10, 1),
        target_date=date(2026, 10, 29),
    )
