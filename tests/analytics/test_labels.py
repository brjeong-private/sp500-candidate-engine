import uuid
from datetime import date, timedelta

import pytest

from sp500_candidate_engine.analytics.labels import (
    LabelCorporateAction,
    LabelPrice,
    generate_excess_return_labels,
    generate_forward_return_labels,
    generate_total_return_labels,
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


@pytest.mark.parametrize(
    ("stock_exit", "benchmark_exit", "expected"),
    [
        (104.0, 106.0, 0.04),
        (98.0, 95.0, -0.02),
    ],
)
def test_raw_return_label_does_not_subtract_spy(
    stock_exit: float,
    benchmark_exit: float,
    expected: float,
) -> None:
    calendar = tuple(date(2026, 1, day) for day in range(1, 8))
    stock = {session: _price(session, 100, 100) for session in calendar}
    benchmark = {session: _price(session, 100, 100) for session in calendar}
    stock[calendar[5]] = _price(calendar[5], stock_exit, stock_exit)
    benchmark[calendar[5]] = _price(
        calendar[5],
        benchmark_exit,
        benchmark_exit,
    )

    label = generate_forward_return_labels(
        instrument_id=uuid.uuid4(),
        calendar=calendar,
        stock_prices=stock,
        benchmark_prices=benchmark,
        horizon_sessions=5,
    )[0]

    assert label.label_value == pytest.approx(expected)
    assert label.raw_return == pytest.approx(expected)


def test_raw_return_label_does_not_require_spy() -> None:
    calendar = tuple(date(2026, 1, day) for day in range(1, 8))
    stock = {session: _price(session, 100, 100) for session in calendar}
    stock[calendar[5]] = _price(calendar[5], 103, 103)

    label = generate_forward_return_labels(
        instrument_id=uuid.uuid4(),
        calendar=calendar,
        stock_prices=stock,
        benchmark_prices=None,
        horizon_sessions=5,
    )[0]

    assert label.label_value == pytest.approx(0.03)
    assert label.benchmark_return is None
    assert label.entry_session_date == calendar[1]
    assert label.exit_session_date == calendar[5]


def test_twenty_session_label_uses_next_open_and_d_plus_twenty_close() -> None:
    calendar = tuple(date(2026, 1, 1 + offset) for offset in range(22))
    stock = {session: _price(session, 100, 100) for session in calendar}
    stock[calendar[20]] = _price(calendar[20], 125, 125)

    label = generate_forward_return_labels(
        instrument_id=uuid.uuid4(),
        calendar=calendar,
        stock_prices=stock,
        benchmark_prices=None,
        horizon_sessions=20,
    )[0]

    assert label.entry_session_date == calendar[1]
    assert label.exit_session_date == calendar[20]
    assert label.label_value == pytest.approx(0.25)


def test_twenty_session_total_return_keeps_dividends_as_cash_and_changes_quantity() -> None:
    calendar = tuple(date(2026, 1, 1) + timedelta(days=index) for index in range(22))
    prices = {session: _price(session, 100, 100) for session in calendar}
    prices[calendar[20]] = _price(calendar[20], 50, 50)

    label = generate_total_return_labels(
        instrument_id=uuid.uuid4(),
        calendar=calendar,
        stock_prices=prices,
        corporate_actions=(
            LabelCorporateAction(
                effective_date=calendar[10],
                action_type="SPLIT",
                split_from=1,
                split_to=2,
            ),
            LabelCorporateAction(
                effective_date=calendar[15],
                action_type="DIVIDEND",
                cash_amount=1,
            ),
        ),
    )[0]

    # Buy one share for 100, split to two, receive $2 cash, exit value is $102.
    assert label.raw_return == pytest.approx(0.02)
    assert label.label_value == pytest.approx(0.02)
    assert label.exit_session_date == calendar[20]
    assert label.quality_status == "OK"


def test_total_return_label_fails_closed_on_duplicate_split_actions() -> None:
    calendar = tuple(date(2026, 1, 1) + timedelta(days=index) for index in range(22))
    prices = {session: _price(session, 100, 100) for session in calendar}

    label = generate_total_return_labels(
        instrument_id=uuid.uuid4(),
        calendar=calendar,
        stock_prices=prices,
        corporate_actions=(
            LabelCorporateAction(
                effective_date=calendar[10],
                action_type="SPLIT",
                split_from=1,
                split_to=2,
            ),
            LabelCorporateAction(
                effective_date=calendar[10],
                action_type="SPLIT",
                split_from=1,
                split_to=3,
            ),
        ),
    )[0]

    assert label.label_value is None
    assert label.quality_status == "INVALID_CORPORATE_ACTION"
