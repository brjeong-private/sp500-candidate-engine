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
