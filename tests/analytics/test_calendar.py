from datetime import date

from sp500_candidate_engine.analytics.calendar import build_exchange_calendar


def test_xnys_calendar_excludes_holiday_and_marks_early_close() -> None:
    dataset = build_exchange_calendar(
        exchange_mic="XNYS",
        start_date=date(2026, 11, 25),
        end_date=date(2026, 11, 27),
    )

    assert [item.session_date for item in dataset.sessions] == [
        date(2026, 11, 25),
        date(2026, 11, 27),
    ]
    assert dataset.sessions[0].is_early_close is False
    assert dataset.sessions[1].is_early_close is True
    assert len(dataset.version_hash) == 64


def test_calendar_hash_is_deterministic() -> None:
    first = build_exchange_calendar(
        exchange_mic="XNYS",
        start_date=date(2026, 1, 2),
        end_date=date(2026, 1, 9),
    )
    second = build_exchange_calendar(
        exchange_mic="XNYS",
        start_date=date(2026, 1, 2),
        end_date=date(2026, 1, 9),
    )

    assert first == second
