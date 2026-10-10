from __future__ import annotations

import math
from dataclasses import dataclass

from sp500_candidate_engine.analytics.export_models import QlibExportDataset


class ExportQualityError(ValueError):
    """Raised when blocking export quality issues are present."""


@dataclass(frozen=True)
class ExportQualityIssue:
    code: str
    entity_key: str
    message: str
    blocking: bool


def validate_export_dataset(
    dataset: QlibExportDataset,
    *,
    large_step_threshold: float = 0.2,
) -> tuple[ExportQualityIssue, ...]:
    issues: list[ExportQualityIssue] = []
    if not dataset.calendar:
        issues.append(
            ExportQualityIssue("EMPTY_CALENDAR", "calendar", "Calendar is empty", True)
        )
        return tuple(issues)
    if tuple(sorted(set(dataset.calendar))) != dataset.calendar:
        issues.append(
            ExportQualityIssue(
                "INVALID_CALENDAR",
                "calendar",
                "Calendar must be sorted and unique",
                True,
            )
        )

    span_by_instrument = {}
    symbols: set[str] = set()
    for span in dataset.instrument_spans:
        if span.instrument_id in span_by_instrument:
            issues.append(
                ExportQualityIssue(
                    "DUPLICATE_INSTRUMENT_SPAN",
                    str(span.instrument_id),
                    "Instrument span is duplicated",
                    True,
                )
            )
        if span.symbol in symbols:
            issues.append(
                ExportQualityIssue(
                    "DUPLICATE_SYMBOL",
                    span.symbol,
                    "Qlib symbol maps to multiple instruments",
                    True,
                )
            )
        if span.start_date > span.end_date:
            issues.append(
                ExportQualityIssue(
                    "INVALID_INSTRUMENT_SPAN",
                    span.symbol,
                    "Instrument start date is after end date",
                    True,
                )
            )
        span_by_instrument[span.instrument_id] = span
        symbols.add(span.symbol)

    calendar_set = set(dataset.calendar)
    seen: set[tuple[object, object]] = set()
    values_by_instrument: dict[object, dict[object, object]] = {}
    for value in dataset.daily_values:
        key = (value.instrument_id, value.session_date)
        if key in seen:
            issues.append(
                ExportQualityIssue(
                    "DUPLICATE_DAILY_VALUE",
                    f"{value.instrument_id}:{value.session_date}",
                    "Instrument and session must be unique",
                    True,
                )
            )
        seen.add(key)
        span = span_by_instrument.get(value.instrument_id)
        if span is None or span.symbol != value.symbol:
            issues.append(
                ExportQualityIssue(
                    "MISSING_INSTRUMENT_SPAN",
                    value.symbol,
                    "Daily value has no matching instrument span",
                    True,
                )
            )
        elif not span.start_date <= value.session_date <= span.end_date:
            issues.append(
                ExportQualityIssue(
                    "VALUE_OUTSIDE_SPAN",
                    f"{value.symbol}:{value.session_date}",
                    "Daily value is outside its instrument span",
                    True,
                )
            )
        if value.session_date not in calendar_set:
            issues.append(
                ExportQualityIssue(
                    "VALUE_OUTSIDE_CALENDAR",
                    f"{value.symbol}:{value.session_date}",
                    "Daily value is outside the export calendar",
                    True,
                )
            )
        prices = (value.open, value.high, value.low, value.close)
        if not all(math.isfinite(item) and item > 0 for item in prices):
            issues.append(
                ExportQualityIssue(
                    "INVALID_PRICE",
                    f"{value.symbol}:{value.session_date}",
                    "OHLC values must be finite and positive",
                    True,
                )
            )
        if value.low > value.high or not value.low <= value.open <= value.high:
            issues.append(
                ExportQualityIssue(
                    "INVALID_OHLC_RANGE",
                    f"{value.symbol}:{value.session_date}",
                    "OHLC values violate the daily range",
                    True,
                )
            )
        if not value.low <= value.close <= value.high:
            issues.append(
                ExportQualityIssue(
                    "INVALID_OHLC_RANGE",
                    f"{value.symbol}:{value.session_date}",
                    "Close is outside the daily range",
                    True,
                )
            )
        if not math.isfinite(value.factor) or value.factor <= 0:
            issues.append(
                ExportQualityIssue(
                    "INVALID_FACTOR",
                    f"{value.symbol}:{value.session_date}",
                    "Adjustment factor must be finite and positive",
                    True,
                )
            )
        if not math.isfinite(value.volume) or value.volume < 0:
            issues.append(
                ExportQualityIssue(
                    "INVALID_VOLUME",
                    f"{value.symbol}:{value.session_date}",
                    "Volume must be finite and non-negative",
                    True,
                )
            )
        if value.change is not None and abs(value.change) > large_step_threshold:
            issues.append(
                ExportQualityIssue(
                    "LARGE_PRICE_STEP",
                    f"{value.symbol}:{value.session_date}",
                    f"Absolute adjusted return exceeds {large_step_threshold:.2%}",
                    False,
                )
            )
        values_by_instrument.setdefault(value.instrument_id, {})[value.session_date] = value

    for instrument_id, by_date in values_by_instrument.items():
        for index, session in enumerate(dataset.calendar):
            current = by_date.get(session)
            if current is None or index == 0:
                continue
            previous = by_date.get(dataset.calendar[index - 1])
            if previous is None and current.change is not None:
                issues.append(
                    ExportQualityIssue(
                        "MULTIDAY_CHANGE",
                        f"{instrument_id}:{session}",
                        "Change must be null when the previous exchange session is missing",
                        True,
                    )
                )
            if previous is not None and current.change is None:
                issues.append(
                    ExportQualityIssue(
                        "MISSING_CHANGE",
                        f"{instrument_id}:{session}",
                        "Change is missing despite a previous exchange session value",
                        True,
                    )
                )
    return tuple(issues)


def ensure_export_quality(dataset: QlibExportDataset) -> tuple[ExportQualityIssue, ...]:
    issues = validate_export_dataset(dataset)
    blocking = [issue for issue in issues if issue.blocking]
    if blocking:
        summary = ", ".join(f"{issue.code}:{issue.entity_key}" for issue in blocking)
        raise ExportQualityError(summary)
    return issues
