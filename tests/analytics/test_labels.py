import uuid
from datetime import date

import pytest

from sp500_candidate_engine.analytics.labels import (
    LabelPrice,
    generate_excess_return_labels,
)


def _price(session: date, open_value: float, close_value: float) -> LabelPrice:
    return LabelPrice(session_date=session, open=open_value, close=close_value)


def test_five_session_label_uses_next_open_and_d_plus_five_close() -> None:
    calendar = tuple(date(2026, 1, day) for day in range(1, 8))
    instrument_id = uuid.uuid4()
    stock = {
        session: _price(session, 100 + index, 100 + index)
        for index, session in enumerate(calendar)
    }
    benchmark = {
        session: _price(session, 200 + index, 200 + index)
        for index, session in enumerate(calendar)
    }

    labels = generate_excess_return_labels(
        instrument_id=instrument_id,
        calendar=calendar,
        stock_prices=stock,
        benchmark_prices=benchmark,
        horizon_sessions=5,
    )

    first = labels[0]
    assert first.anchor_session_date == calendar[0]
    assert first.entry_session_date == calendar[1]
    assert first.exit_session_date == calendar[5]
    stock_return = stock[calendar[5]].close / stock[calendar[1]].open - 1
    benchmark_return = (
        benchmark[calendar[5]].close / benchmark[calendar[1]].open - 1
    )
    assert first.label_value == pytest.approx(stock_return - benchmark_return)
    assert first.quality_status == "OK"


def test_label_crossing_segment_end_is_purged() -> None:
    calendar = tuple(date(2026, 1, day) for day in range(1, 8))
    prices = {session: _price(session, 100, 101) for session in calendar}

    labels = generate_excess_return_labels(
        instrument_id=uuid.uuid4(),
        calendar=calendar,
        stock_prices=prices,
        benchmark_prices=prices,
        horizon_sessions=5,
        segment_end=calendar[4],
    )

    assert labels[0].label_value is None
    assert labels[0].quality_status == "PURGED_BOUNDARY"


def test_missing_exit_price_is_preserved_as_quality_state() -> None:
    calendar = tuple(date(2026, 1, day) for day in range(1, 8))
    prices = {session: _price(session, 100, 101) for session in calendar}
    del prices[calendar[5]]

    labels = generate_excess_return_labels(
        instrument_id=uuid.uuid4(),
        calendar=calendar,
        stock_prices=prices,
        benchmark_prices={
            session: _price(session, 200, 201) for session in calendar
        },
        horizon_sessions=5,
    )

    assert labels[0].label_value is None
    assert labels[0].quality_status == "MISSING_STOCK_PRICE"
