import uuid
from datetime import date, datetime

import pytest

from sp500_candidate_engine.analytics.export_models import (
    InstrumentSpan,
    QlibDailyValue,
    QlibExportDataset,
)
from sp500_candidate_engine.analytics.quality import (
    ExportQualityError,
    ensure_export_quality,
    validate_export_dataset,
)
from sp500_candidate_engine.models import UTC


def _dataset(*, duplicate: bool = False) -> QlibExportDataset:
    instrument_id = uuid.uuid4()
    dates = (date(2026, 1, 2), date(2026, 1, 5))
    first = QlibDailyValue(
        instrument_id=instrument_id,
        symbol="TEST",
        session_date=dates[0],
        open=10,
        high=11,
        low=9,
        close=10,
        volume=100,
        vwap=10,
        factor=1,
        change=None,
        quality_status="WARMUP",
    )
    second = QlibDailyValue(
        instrument_id=instrument_id,
        symbol="TEST",
        session_date=dates[1],
        open=11,
        high=12,
        low=10,
        close=11,
        volume=110,
        vwap=11,
        factor=1,
        change=0.1,
        quality_status="OK",
    )
    values = (first, second, second) if duplicate else (first, second)
    return QlibExportDataset(
        export_run_id=uuid.uuid4(),
        execution_context_id=uuid.uuid4(),
        universe_version_id=uuid.uuid4(),
        cutoff_at=datetime(2026, 1, 6, 10, 30, tzinfo=UTC),
        adjustment_policy="SPLIT_ONLY",
        calendar=dates,
        instrument_spans=(
            InstrumentSpan(
                instrument_id=instrument_id,
                symbol="TEST",
                start_date=dates[0],
                end_date=dates[-1],
            ),
        ),
        daily_values=values,
    )


def test_export_quality_accepts_valid_dataset() -> None:
    issues = validate_export_dataset(_dataset())

    assert not [issue for issue in issues if issue.blocking]


def test_export_quality_blocks_duplicate_instrument_date() -> None:
    dataset = _dataset(duplicate=True)

    with pytest.raises(ExportQualityError, match="DUPLICATE_DAILY_VALUE"):
        ensure_export_quality(dataset)


def test_export_quality_blocks_invalid_factor() -> None:
    dataset = _dataset()
    invalid = dataset.daily_values[1]
    dataset = QlibExportDataset(
        export_run_id=dataset.export_run_id,
        execution_context_id=dataset.execution_context_id,
        universe_version_id=dataset.universe_version_id,
        cutoff_at=dataset.cutoff_at,
        adjustment_policy=dataset.adjustment_policy,
        calendar=dataset.calendar,
        instrument_spans=dataset.instrument_spans,
        daily_values=(
            dataset.daily_values[0],
            QlibDailyValue(
                instrument_id=invalid.instrument_id,
                symbol=invalid.symbol,
                session_date=invalid.session_date,
                open=invalid.open,
                high=invalid.high,
                low=invalid.low,
                close=invalid.close,
                volume=invalid.volume,
                vwap=invalid.vwap,
                factor=0,
                change=invalid.change,
                quality_status=invalid.quality_status,
            ),
        ),
    )

    with pytest.raises(ExportQualityError, match="INVALID_FACTOR"):
        ensure_export_quality(dataset)


def test_export_quality_flags_large_step_without_mutating_value() -> None:
    dataset = _dataset()
    value = dataset.daily_values[1]
    dataset = QlibExportDataset(
        export_run_id=dataset.export_run_id,
        execution_context_id=dataset.execution_context_id,
        universe_version_id=dataset.universe_version_id,
        cutoff_at=dataset.cutoff_at,
        adjustment_policy=dataset.adjustment_policy,
        calendar=dataset.calendar,
        instrument_spans=dataset.instrument_spans,
        daily_values=(
            dataset.daily_values[0],
            QlibDailyValue(
                instrument_id=value.instrument_id,
                symbol=value.symbol,
                session_date=value.session_date,
                open=value.open,
                high=value.high,
                low=value.low,
                close=value.close,
                volume=value.volume,
                vwap=value.vwap,
                factor=value.factor,
                change=0.25,
                quality_status=value.quality_status,
            ),
        ),
    )

    issues = ensure_export_quality(dataset)

    assert [issue.code for issue in issues] == ["LARGE_PRICE_STEP"]
