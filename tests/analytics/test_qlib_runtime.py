import uuid
from datetime import date, datetime

import pytest

pytest.importorskip("qlib")

from sp500_candidate_engine.analytics.calendar import build_exchange_calendar
from sp500_candidate_engine.analytics.export_models import (
    InstrumentSpan,
    QlibDailyValue,
    QlibExportDataset,
)
from sp500_candidate_engine.analytics.features import Alpha158FeatureService
from sp500_candidate_engine.analytics.qlib_exporter import QlibBinaryExporter
from sp500_candidate_engine.models import UTC


def test_exported_dataset_loads_alpha158(tmp_path) -> None:
    calendar = build_exchange_calendar(
        exchange_mic="XNYS",
        start_date=date(2025, 1, 2),
        end_date=date(2026, 1, 30),
    )
    instrument_id = uuid.uuid4()
    previous_close: float | None = None
    values = []
    for index, session in enumerate(calendar.sessions):
        close = 100 + index * 0.1
        change = None if previous_close is None else close / previous_close - 1
        values.append(
            QlibDailyValue(
                instrument_id=instrument_id,
                symbol="TEST",
                session_date=session.session_date,
                open=close,
                high=close + 1,
                low=close - 1,
                close=close,
                volume=100_000 + index,
                vwap=close,
                factor=1,
                change=change,
                quality_status="WARMUP" if previous_close is None else "OK",
            )
        )
        previous_close = close
    dataset = QlibExportDataset(
        export_run_id=uuid.uuid4(),
        execution_context_id=uuid.uuid4(),
        universe_version_id=uuid.uuid4(),
        cutoff_at=datetime(2026, 2, 2, 10, 30, tzinfo=UTC),
        adjustment_policy="SPLIT_ONLY",
        calendar=tuple(session.session_date for session in calendar.sessions),
        instrument_spans=(
            InstrumentSpan(
                instrument_id=instrument_id,
                symbol="TEST",
                start_date=calendar.sessions[0].session_date,
                end_date=calendar.sessions[-1].session_date,
            ),
        ),
        daily_values=tuple(values),
    )
    export = QlibBinaryExporter().export(dataset=dataset, output_root=tmp_path)

    result = Alpha158FeatureService().compute_raw(
        provider_uri=export.export_dir / "qlib_data",
        instruments="all",
        start_date=calendar.sessions[0].session_date,
        end_date=calendar.sessions[-1].session_date,
    )

    assert result.frame.shape == (len(calendar.sessions), 158)
