from datetime import date, datetime

import pytest

from sp500_candidate_engine.analytics.adjustments import (
    AdjustmentError,
    AdjustmentPolicy,
    RawDailyValue,
    adjust_daily_values,
)
from sp500_candidate_engine.models import UTC
from sp500_candidate_engine.production_models import CorporateAction


def _split(
    *,
    action_id: str,
    effective_date: date,
    split_from: float,
    split_to: float,
) -> CorporateAction:
    return CorporateAction(
        provider_action_id=action_id,
        symbol="TEST",
        action_type="SPLIT",
        effective_date=effective_date,
        declaration_date=None,
        record_date=None,
        pay_date=None,
        cash_amount=None,
        currency=None,
        split_from=split_from,
        split_to=split_to,
        source_available_at=datetime(2026, 1, 1, tzinfo=UTC),
        metadata={},
    )


def _dividend(*, effective_date: date, cash_amount: float) -> CorporateAction:
    return CorporateAction(
        provider_action_id="dividend",
        symbol="TEST",
        action_type="DIVIDEND",
        effective_date=effective_date,
        declaration_date=effective_date,
        record_date=None,
        pay_date=None,
        cash_amount=cash_amount,
        currency="USD",
        split_from=None,
        split_to=None,
        source_available_at=datetime(2026, 1, 1, tzinfo=UTC),
        metadata={},
    )


def _bar(session_date: date, close: float, volume: int = 100) -> RawDailyValue:
    return RawDailyValue(
        session_date=session_date,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=volume,
        vwap=close,
    )


def test_split_adjustment_changes_pre_split_price_and_volume() -> None:
    calendar = (date(2026, 1, 2), date(2026, 1, 5), date(2026, 1, 6))
    values = adjust_daily_values(
        bars=(
            _bar(calendar[0], 100, 100),
            _bar(calendar[1], 50, 200),
            _bar(calendar[2], 55, 220),
        ),
        actions=(
            _split(
                action_id="split",
                effective_date=calendar[1],
                split_from=1,
                split_to=2,
            ),
        ),
        calendar=calendar,
        policy=AdjustmentPolicy.SPLIT_ONLY,
    )

    assert values[0].factor == pytest.approx(0.5)
    assert values[0].close == pytest.approx(50)
    assert values[0].volume == pytest.approx(200)
    assert values[1].factor == pytest.approx(1)
    assert values[1].change == pytest.approx(0)
    assert values[2].change == pytest.approx(0.1)


def test_total_return_policy_applies_cash_dividend_before_ex_date() -> None:
    calendar = (date(2026, 1, 2), date(2026, 1, 5))
    values = adjust_daily_values(
        bars=(_bar(calendar[0], 100), _bar(calendar[1], 99)),
        actions=(_dividend(effective_date=calendar[1], cash_amount=1),),
        calendar=calendar,
        policy=AdjustmentPolicy.TOTAL_RETURN,
    )

    assert values[0].factor == pytest.approx(0.99)
    assert values[0].close == pytest.approx(99)
    assert values[1].change == pytest.approx(0)


def test_missing_previous_exchange_session_does_not_create_multiday_change() -> None:
    calendar = (date(2026, 1, 2), date(2026, 1, 5), date(2026, 1, 6))
    values = adjust_daily_values(
        bars=(_bar(calendar[0], 100), _bar(calendar[2], 110)),
        actions=(),
        calendar=calendar,
        policy=AdjustmentPolicy.SPLIT_ONLY,
    )

    assert values[1].change is None
    assert values[1].quality_status == "MISSING_PREVIOUS_SESSION"


def test_conflicting_split_revisions_are_blocking() -> None:
    session = date(2026, 1, 5)
    with pytest.raises(AdjustmentError, match="Conflicting split ratios"):
        adjust_daily_values(
            bars=(_bar(date(2026, 1, 2), 100), _bar(session, 50)),
            actions=(
                _split(
                    action_id="split-a",
                    effective_date=session,
                    split_from=1,
                    split_to=2,
                ),
                _split(
                    action_id="split-b",
                    effective_date=session,
                    split_from=1,
                    split_to=3,
                ),
            ),
            calendar=(date(2026, 1, 2), session),
            policy=AdjustmentPolicy.SPLIT_ONLY,
        )
