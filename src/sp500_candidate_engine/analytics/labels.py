from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class LabelPrice:
    session_date: date
    open: float
    close: float


@dataclass(frozen=True)
class LabelCorporateAction:
    effective_date: date
    action_type: str
    cash_amount: float | None = None
    split_from: float | None = None
    split_to: float | None = None


@dataclass(frozen=True)
class DailyLabelValue:
    instrument_id: uuid.UUID
    anchor_session_date: date
    entry_session_date: date
    exit_session_date: date
    raw_return: float | None
    benchmark_return: float | None
    label_value: float | None
    quality_status: str


def _valid_price(price: LabelPrice | None) -> bool:
    return (
        price is not None
        and math.isfinite(price.open)
        and price.open > 0
        and math.isfinite(price.close)
        and price.close > 0
    )


def generate_excess_return_labels(
    *,
    instrument_id: uuid.UUID,
    calendar: tuple[date, ...],
    stock_prices: dict[date, LabelPrice],
    benchmark_prices: dict[date, LabelPrice],
    horizon_sessions: int,
    segment_end: date | None = None,
) -> tuple[DailyLabelValue, ...]:
    if horizon_sessions < 1:
        raise ValueError("horizon_sessions must be positive")
    if tuple(sorted(set(calendar))) != calendar:
        raise ValueError("calendar must be sorted and unique")
    labels: list[DailyLabelValue] = []
    for anchor_index in range(max(0, len(calendar) - horizon_sessions)):
        anchor = calendar[anchor_index]
        entry = calendar[anchor_index + 1]
        exit_session = calendar[anchor_index + horizon_sessions]
        if segment_end is not None and exit_session > segment_end:
            labels.append(
                DailyLabelValue(
                    instrument_id=instrument_id,
                    anchor_session_date=anchor,
                    entry_session_date=entry,
                    exit_session_date=exit_session,
                    raw_return=None,
                    benchmark_return=None,
                    label_value=None,
                    quality_status="PURGED_BOUNDARY",
                )
            )
            continue
        stock_entry = stock_prices.get(entry)
        stock_exit = stock_prices.get(exit_session)
        benchmark_entry = benchmark_prices.get(entry)
        benchmark_exit = benchmark_prices.get(exit_session)
        if not _valid_price(stock_entry) or not _valid_price(stock_exit):
            quality_status = "MISSING_STOCK_PRICE"
            raw_return = benchmark_return = label_value = None
        elif not _valid_price(benchmark_entry) or not _valid_price(benchmark_exit):
            quality_status = "MISSING_BENCHMARK_PRICE"
            raw_return = benchmark_return = label_value = None
        else:
            assert stock_entry is not None
            assert stock_exit is not None
            assert benchmark_entry is not None
            assert benchmark_exit is not None
            raw_return = stock_exit.close / stock_entry.open - 1
            benchmark_return = benchmark_exit.close / benchmark_entry.open - 1
            label_value = raw_return - benchmark_return
            quality_status = "OK"
        labels.append(
            DailyLabelValue(
                instrument_id=instrument_id,
                anchor_session_date=anchor,
                entry_session_date=entry,
                exit_session_date=exit_session,
                raw_return=raw_return,
                benchmark_return=benchmark_return,
                label_value=label_value,
                quality_status=quality_status,
            )
        )
    return tuple(labels)


def generate_forward_return_labels(
    *,
    instrument_id: uuid.UUID,
    calendar: tuple[date, ...],
    stock_prices: dict[date, LabelPrice],
    benchmark_prices: dict[date, LabelPrice] | None,
    horizon_sessions: int,
    segment_end: date | None = None,
) -> tuple[DailyLabelValue, ...]:
    if horizon_sessions < 1:
        raise ValueError("horizon_sessions must be positive")
    if tuple(sorted(set(calendar))) != calendar:
        raise ValueError("calendar must be sorted and unique")
    labels: list[DailyLabelValue] = []
    for anchor_index in range(max(0, len(calendar) - horizon_sessions)):
        anchor = calendar[anchor_index]
        entry = calendar[anchor_index + 1]
        exit_session = calendar[anchor_index + horizon_sessions]
        if segment_end is not None and exit_session > segment_end:
            labels.append(
                DailyLabelValue(
                    instrument_id=instrument_id,
                    anchor_session_date=anchor,
                    entry_session_date=entry,
                    exit_session_date=exit_session,
                    raw_return=None,
                    benchmark_return=None,
                    label_value=None,
                    quality_status="PURGED_BOUNDARY",
                )
            )
            continue
        stock_entry = stock_prices.get(entry)
        stock_exit = stock_prices.get(exit_session)
        if not _valid_price(stock_entry) or not _valid_price(stock_exit):
            raw_return = benchmark_return = label_value = None
            quality_status = "MISSING_STOCK_PRICE"
        else:
            assert stock_entry is not None
            assert stock_exit is not None
            raw_return = stock_exit.close / stock_entry.open - 1
            benchmark_return = None
            if benchmark_prices is not None:
                benchmark_entry = benchmark_prices.get(entry)
                benchmark_exit = benchmark_prices.get(exit_session)
                if _valid_price(benchmark_entry) and _valid_price(benchmark_exit):
                    assert benchmark_entry is not None
                    assert benchmark_exit is not None
                    benchmark_return = (
                        benchmark_exit.close / benchmark_entry.open - 1
                    )
            label_value = raw_return
            quality_status = "OK"
        labels.append(
            DailyLabelValue(
                instrument_id=instrument_id,
                anchor_session_date=anchor,
                entry_session_date=entry,
                exit_session_date=exit_session,
                raw_return=raw_return,
                benchmark_return=benchmark_return,
                label_value=label_value,
                quality_status=quality_status,
            )
        )
    return tuple(labels)


def generate_total_return_labels(
    *,
    instrument_id: uuid.UUID,
    calendar: tuple[date, ...],
    stock_prices: dict[date, LabelPrice],
    corporate_actions: tuple[LabelCorporateAction, ...],
    horizon_sessions: int = 20,
    segment_end: date | None = None,
) -> tuple[DailyLabelValue, ...]:
    """Return cash-inclusive holding-period labels without dividend reinvestment.

    One share is bought at D+1 open. Splits strictly after entry change quantity;
    cash dividends strictly after entry are accumulated using quantity at the
    action date. Both policies avoid granting an ex-date entitlement to a buyer
    entering at that session's open.
    """
    if horizon_sessions < 1:
        raise ValueError("horizon_sessions must be positive")
    if tuple(sorted(set(calendar))) != calendar:
        raise ValueError("calendar must be sorted and unique")
    ordered_actions = sorted(
        corporate_actions,
        key=lambda action: (
            action.effective_date,
            0 if action.action_type == "SPLIT" else 1,
        ),
    )
    split_dates: set[date] = set()
    duplicate_split_dates: set[date] = set()
    for action in ordered_actions:
        if action.action_type != "SPLIT":
            continue
        if action.effective_date in split_dates:
            duplicate_split_dates.add(action.effective_date)
        split_dates.add(action.effective_date)
    labels: list[DailyLabelValue] = []
    for anchor_index in range(max(0, len(calendar) - horizon_sessions)):
        anchor = calendar[anchor_index]
        entry = calendar[anchor_index + 1]
        exit_session = calendar[anchor_index + horizon_sessions]
        if segment_end is not None and exit_session > segment_end:
            quality_status = "PURGED_BOUNDARY"
            raw_return = None
        else:
            entry_price = stock_prices.get(entry)
            exit_price = stock_prices.get(exit_session)
            if not _valid_price(entry_price) or not _valid_price(exit_price):
                quality_status = "MISSING_STOCK_PRICE"
                raw_return = None
            else:
                assert entry_price is not None
                assert exit_price is not None
                quantity = 1.0
                cash = 0.0
                quality_status = "OK"
                for action in ordered_actions:
                    if not entry < action.effective_date <= exit_session:
                        continue
                    if action.action_type == "SPLIT":
                        if action.effective_date in duplicate_split_dates:
                            quality_status = "INVALID_CORPORATE_ACTION"
                            break
                        if (
                            action.split_from is None
                            or action.split_to is None
                            or action.split_from <= 0
                            or action.split_to <= 0
                        ):
                            quality_status = "INVALID_CORPORATE_ACTION"
                            break
                        quantity *= action.split_to / action.split_from
                    elif action.action_type == "DIVIDEND":
                        if (
                            action.cash_amount is None
                            or not math.isfinite(action.cash_amount)
                            or action.cash_amount < 0
                        ):
                            quality_status = "INVALID_CORPORATE_ACTION"
                            break
                        cash += quantity * action.cash_amount
                    else:
                        quality_status = "INVALID_CORPORATE_ACTION"
                        break
                raw_return = (
                    quantity * exit_price.close + cash
                ) / entry_price.open - 1 if quality_status == "OK" else None
        labels.append(
            DailyLabelValue(
                instrument_id=instrument_id,
                anchor_session_date=anchor,
                entry_session_date=entry,
                exit_session_date=exit_session,
                raw_return=raw_return,
                benchmark_return=None,
                label_value=raw_return,
                quality_status=quality_status,
            )
        )
    return tuple(labels)
