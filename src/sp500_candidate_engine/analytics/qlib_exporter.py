from __future__ import annotations

import csv
import hashlib
import json
import math
import shutil
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from urllib.parse import quote

import numpy as np

from sp500_candidate_engine.analytics.export_models import (
    QlibDailyValue,
    QlibExportDataset,
    QlibExportResult,
)
from sp500_candidate_engine.analytics.quality import ensure_export_quality
from sp500_candidate_engine.database import _canonical_hash

SCHEMA_VERSION = "qlib-daily-v1"
EXPORTER_VERSION = "1"
FIELDS = ("open", "high", "low", "close", "volume", "vwap", "factor", "change")


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _symbol_directory(symbol: str) -> str:
    return quote(symbol.lower(), safe="-_")


class QlibBinaryExporter:
    def export(
        self,
        *,
        dataset: QlibExportDataset,
        output_root: Path,
    ) -> QlibExportResult:
        ensure_export_quality(dataset)
        output_root = Path(output_root)
        export_dir = output_root / str(dataset.export_run_id)
        manifest_path = export_dir / "manifest.json"
        content_hash = _canonical_hash(
            {
                "schema_version": SCHEMA_VERSION,
                "execution_context_id": dataset.execution_context_id,
                "universe_version_id": dataset.universe_version_id,
                "cutoff_at": dataset.cutoff_at,
                "adjustment_policy": dataset.adjustment_policy,
                "calendar": dataset.calendar,
                "instrument_spans": dataset.instrument_spans,
                "daily_values": dataset.daily_values,
            }
        )
        if export_dir.exists():
            if not manifest_path.exists():
                raise FileExistsError(f"Existing export has no manifest: {export_dir}")
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
            if existing.get("content_hash") != content_hash:
                raise FileExistsError(
                    f"Export run already exists with different content: {export_dir}"
                )
            return QlibExportResult(
                export_dir=export_dir,
                manifest_path=manifest_path,
                content_hash=content_hash,
                row_count=int(existing["row_count"]),
            )

        output_root.mkdir(parents=True, exist_ok=True)
        temporary_dir = output_root / f".{dataset.export_run_id}.tmp"
        if temporary_dir.exists():
            shutil.rmtree(temporary_dir)
        try:
            self._write_export(dataset=dataset, target_dir=temporary_dir)
            artifacts = {
                str(path.relative_to(temporary_dir)).replace("\\", "/"): _file_hash(path)
                for path in sorted(temporary_dir.rglob("*"))
                if path.is_file()
            }
            manifest = {
                "schema_version": SCHEMA_VERSION,
                "exporter_version": EXPORTER_VERSION,
                "export_run_id": str(dataset.export_run_id),
                "execution_context_id": str(dataset.execution_context_id),
                "universe_version_id": str(dataset.universe_version_id),
                "cutoff_at": dataset.cutoff_at.isoformat(),
                "adjustment_policy": dataset.adjustment_policy,
                "row_count": len(dataset.daily_values),
                "instrument_count": len(dataset.instrument_spans),
                "calendar_start": dataset.calendar[0].isoformat(),
                "calendar_end": dataset.calendar[-1].isoformat(),
                "content_hash": content_hash,
                "artifacts": artifacts,
            }
            (temporary_dir / "manifest.json").write_text(
                json.dumps(manifest, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            temporary_dir.replace(export_dir)
        except Exception:
            if temporary_dir.exists():
                shutil.rmtree(temporary_dir)
            raise
        return QlibExportResult(
            export_dir=export_dir,
            manifest_path=manifest_path,
            content_hash=content_hash,
            row_count=len(dataset.daily_values),
        )

    def _write_export(self, *, dataset: QlibExportDataset, target_dir: Path) -> None:
        qlib_dir = target_dir / "qlib_data"
        calendar_dir = qlib_dir / "calendars"
        instruments_dir = qlib_dir / "instruments"
        features_dir = qlib_dir / "features"
        staging_dir = target_dir / "staging"
        calendar_dir.mkdir(parents=True)
        instruments_dir.mkdir(parents=True)
        features_dir.mkdir(parents=True)
        staging_dir.mkdir(parents=True)

        (calendar_dir / "day.txt").write_text(
            "".join(f"{session.isoformat()}\n" for session in dataset.calendar),
            encoding="utf-8",
        )
        (instruments_dir / "all.txt").write_text(
            "".join(
                f"{span.symbol.upper()}\t{span.start_date.isoformat()}\t"
                f"{span.end_date.isoformat()}\n"
                for span in sorted(dataset.instrument_spans, key=lambda item: item.symbol)
            ),
            encoding="utf-8",
        )
        calendar_index = {
            session: index for index, session in enumerate(dataset.calendar)
        }
        by_symbol: dict[str, list[QlibDailyValue]] = defaultdict(list)
        for value in dataset.daily_values:
            by_symbol[value.symbol].append(value)
        for symbol, rows in sorted(by_symbol.items()):
            ordered = sorted(rows, key=lambda item: item.session_date)
            self._write_staging(staging_dir / f"{_symbol_directory(symbol)}.csv", ordered)
            symbol_dir = features_dir / _symbol_directory(symbol)
            symbol_dir.mkdir()
            first_index = calendar_index[ordered[0].session_date]
            last_index = calendar_index[ordered[-1].session_date]
            by_date = {item.session_date: item for item in ordered}
            sessions = dataset.calendar[first_index : last_index + 1]
            for field in FIELDS:
                values = [
                    self._field_value(by_date.get(session), field)
                    for session in sessions
                ]
                np.asarray([first_index, *values], dtype="<f4").tofile(
                    symbol_dir / f"{field}.day.bin"
                )

    @staticmethod
    def _field_value(value: QlibDailyValue | None, field: str) -> float:
        if value is None:
            return math.nan
        field_value = getattr(value, field)
        return math.nan if field_value is None else float(field_value)

    @staticmethod
    def _write_staging(path: Path, rows: list[QlibDailyValue]) -> None:
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(
                stream,
                fieldnames=("date", "symbol", *FIELDS, "quality_status"),
            )
            writer.writeheader()
            for row in rows:
                payload = asdict(row)
                writer.writerow(
                    {
                        "date": row.session_date.isoformat(),
                        "symbol": row.symbol,
                        **{field: payload[field] for field in FIELDS},
                        "quality_status": row.quality_status,
                    }
                )
