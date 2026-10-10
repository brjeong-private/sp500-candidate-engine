from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path


@dataclass(frozen=True)
class InstrumentSpan:
    instrument_id: uuid.UUID
    symbol: str
    start_date: date
    end_date: date


@dataclass(frozen=True)
class QlibDailyValue:
    instrument_id: uuid.UUID
    symbol: str
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


@dataclass(frozen=True)
class QlibExportDataset:
    export_run_id: uuid.UUID
    execution_context_id: uuid.UUID
    universe_version_id: uuid.UUID
    cutoff_at: datetime
    adjustment_policy: str
    calendar: tuple[date, ...]
    instrument_spans: tuple[InstrumentSpan, ...]
    daily_values: tuple[QlibDailyValue, ...]


@dataclass(frozen=True)
class QlibExportResult:
    export_dir: Path
    manifest_path: Path
    content_hash: str
    row_count: int
