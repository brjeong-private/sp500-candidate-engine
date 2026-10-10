import json
import uuid
from datetime import date, datetime

import numpy as np

from sp500_candidate_engine.analytics.export_models import (
    InstrumentSpan,
    QlibDailyValue,
    QlibExportDataset,
)
from sp500_candidate_engine.analytics.qlib_exporter import QlibBinaryExporter
from sp500_candidate_engine.models import UTC


def _dataset(export_run_id: uuid.UUID) -> QlibExportDataset:
    instrument_id = uuid.uuid4()
    dates = (date(2026, 1, 2), date(2026, 1, 5))
    return QlibExportDataset(
        export_run_id=export_run_id,
        execution_context_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        universe_version_id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
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
        daily_values=(
            QlibDailyValue(
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
            ),
            QlibDailyValue(
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
            ),
        ),
    )


def test_exporter_writes_qlib_layout_and_binary_values(tmp_path) -> None:
    result = QlibBinaryExporter().export(
        dataset=_dataset(uuid.UUID("33333333-3333-3333-3333-333333333333")),
        output_root=tmp_path,
    )

    qlib_dir = result.export_dir / "qlib_data"
    assert (qlib_dir / "calendars" / "day.txt").read_text().splitlines() == [
        "2026-01-02",
        "2026-01-05",
    ]
    assert (qlib_dir / "instruments" / "all.txt").read_text().strip() == (
        "TEST\t2026-01-02\t2026-01-05"
    )
    close = np.fromfile(
        qlib_dir / "features" / "test" / "close.day.bin",
        dtype="<f4",
    )
    assert close.tolist() == [0.0, 10.0, 11.0]

    manifest = json.loads(result.manifest_path.read_text())
    assert manifest["row_count"] == 2
    assert manifest["schema_version"] == "qlib-daily-v1"
    assert manifest["content_hash"] == result.content_hash


def test_exporter_is_idempotent_for_same_run_and_payload(tmp_path) -> None:
    dataset = _dataset(uuid.UUID("44444444-4444-4444-4444-444444444444"))
    exporter = QlibBinaryExporter()

    first = exporter.export(dataset=dataset, output_root=tmp_path)
    second = exporter.export(dataset=dataset, output_root=tmp_path)

    assert first.content_hash == second.content_hash
    assert first.export_dir == second.export_dir
