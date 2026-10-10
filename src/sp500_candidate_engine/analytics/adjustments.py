from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from sp500_candidate_engine.production_models import CorporateAction


class AdjustmentError(ValueError):
    """Raised when corporate actions cannot produce a deterministic factor."""


class AdjustmentPolicy(StrEnum):
    SPLIT_ONLY = "SPLIT_ONLY"
    TOTAL_RETURN = "TOTAL_RETURN"


@dataclass(frozen=True)
class RawDailyValue:
    session_date: date
    open: float
    high: float
    low: float
    close: float
    volume: int
    vwap: float | None


@dataclass(frozen=True)
class AdjustedDailyValue:
    session_date: date
    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap: float | None
    factor: float
    change: float | None
    quality_status: str


def _validate_bars(
    bars: tuple[RawDailyValue, ...],
    calendar: tuple[date, ...],
) -> dict[date, RawDailyValue]:
    if tuple(sorted(set(calendar))) != calendar:
        raise AdjustmentError("Calendar must be sorted and unique")
    by_date: dict[date, RawDailyValue] = {}
    calendar_set = set(calendar)
    for bar in bars:
        if bar.session_date not in calendar_set:
            raise AdjustmentError(f"Bar date is outside the calendar: {bar.session_date}")
        if bar.session_date in by_date:
            raise AdjustmentError(f"Duplicate bar date: {bar.session_date}")
        prices = (bar.open, bar.high, bar.low, bar.close)
        if not all(math.isfinite(value) and value > 0 for value in prices):
            raise AdjustmentError(f"Invalid price at {bar.session_date}")
        if bar.low > bar.high or not bar.low <= bar.open <= bar.high:
            raise AdjustmentError(f"Invalid OHLC range at {bar.session_date}")
        if not bar.low <= bar.close <= bar.high:
            raise AdjustmentError(f"Invalid close range at {bar.session_date}")
        if bar.volume < 0:
            raise AdjustmentError(f"Negative volume at {bar.session_date}")
        by_date[bar.session_date] = bar
    return by_date


def _split_ratios(actions: tuple[CorporateAction, ...]) -> dict[date, float]:
    ratios: dict[date, float] = {}
    for action in actions:
        if action.action_type != "SPLIT":
            continue
        if action.split_from is None or action.split_to is None:
            raise AdjustmentError(f"Split ratio is missing: {action.provider_action_id}")
        if action.split_from <= 0 or action.split_to <= 0:
            raise AdjustmentError(f"Split ratio must be positive: {action.provider_action_id}")
        ratio = action.split_from / action.split_to
        current = ratios.get(action.effective_date)
        if current is not None and not math.isclose(current, ratio, rel_tol=1e-12):
            raise AdjustmentError(
                f"Conflicting split ratios at {action.effective_date}: {current} != {ratio}"
            )
        ratios[action.effective_date] = ratio
    return ratios


def adjust_daily_values(
    *,
    bars: tuple[RawDailyValue, ...],
    actions: tuple[CorporateAction, ...],
    calendar: tuple[date, ...],
    policy: AdjustmentPolicy,
) -> tuple[AdjustedDailyValue, ...]:
    by_date = _validate_bars(bars, calendar)
    calendar_index = {session: index for index, session in enumerate(calendar)}
    price_factors = [1.0] * len(calendar)
    split_factors = [1.0] * len(calendar)

    for effective_date, ratio in sorted(_split_ratios(actions).items()):
        index = calendar_index.get(effective_date)
        if index is None:
            continue
        for position in range(index):
            price_factors[position] *= ratio
            split_factors[position] *= ratio

    if policy is AdjustmentPolicy.TOTAL_RETURN:
        ordered_actions = sorted(
            actions,
            key=lambda item: (item.effective_date, item.provider_action_id),
        )
        for action in ordered_actions:
            if action.action_type != "DIVIDEND":
                continue
            if action.cash_amount is None or action.cash_amount < 0:
                raise AdjustmentError(
                    f"Dividend amount is invalid: {action.provider_action_id}"
                )
            index = calendar_index.get(action.effective_date)
            if index is None or index == 0:
                continue
            previous_session = calendar[index - 1]
            previous_bar = by_date.get(previous_session)
            if previous_bar is None:
                raise AdjustmentError(
                    f"Dividend factor requires previous session close: {previous_session}"
                )
            multiplier = (previous_bar.close - action.cash_amount) / previous_bar.close
            if not 0 < multiplier <= 1:
                raise AdjustmentError(
                    f"Dividend factor is outside (0, 1]: {action.provider_action_id}"
                )
            for position in range(index):
                price_factors[position] *= multiplier

    adjusted_by_date: dict[date, AdjustedDailyValue] = {}
    for session_date, bar in sorted(by_date.items()):
        position = calendar_index[session_date]
        factor = price_factors[position]
        split_factor = split_factors[position]
        adjusted_by_date[session_date] = AdjustedDailyValue(
            session_date=session_date,
            open=bar.open * factor,
            high=bar.high * factor,
            low=bar.low * factor,
            close=bar.close * factor,
            volume=bar.volume / split_factor,
            vwap=None if bar.vwap is None else bar.vwap * factor,
            factor=factor,
            change=None,
            quality_status="OK",
        )

    result: list[AdjustedDailyValue] = []
    for session_date in sorted(adjusted_by_date):
        current = adjusted_by_date[session_date]
        position = calendar_index[session_date]
        previous = (
            adjusted_by_date.get(calendar[position - 1])
            if position > 0
            else None
        )
        if previous is None:
            quality_status = "WARMUP" if position == 0 else "MISSING_PREVIOUS_SESSION"
            change = None
        else:
            quality_status = "OK"
            change = current.close / previous.close - 1
        result.append(
            AdjustedDailyValue(
                session_date=current.session_date,
                open=current.open,
                high=current.high,
                low=current.low,
                close=current.close,
                volume=current.volume,
                vwap=current.vwap,
                factor=current.factor,
                change=change,
                quality_status=quality_status,
            )
        )
    return tuple(result)
