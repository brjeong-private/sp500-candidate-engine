from __future__ import annotations

import json
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

UTC = ZoneInfo("UTC")
SEOUL = ZoneInfo("Asia/Seoul")


@dataclass
class PipelineStage:
    logger: PipelineLogger
    collection_date: date
    pipeline_name: str
    started_at: datetime
    started_counter: float
    details: dict[str, Any]
    completion_status: str = "SUCCESS"
    completion_reason: str | None = None

    def add_details(self, **values: Any) -> None:
        self.details.update(values)

    def mark_partial_success(self, reason: str) -> None:
        self.completion_status = "PARTIAL_SUCCESS"
        self.completion_reason = reason


class PipelineLogger:
    _lock = threading.Lock()

    def __init__(self, log_dir: Path) -> None:
        self.log_dir = log_dir

    @contextmanager
    def stage(
        self,
        collection_date: date,
        pipeline_name: str,
        **initial_details: Any,
    ) -> Generator[PipelineStage, None, None]:
        stage = PipelineStage(
            logger=self,
            collection_date=collection_date,
            pipeline_name=pipeline_name,
            started_at=datetime.now(UTC),
            started_counter=time.perf_counter(),
            details=dict(initial_details),
        )
        try:
            yield stage
        except Exception as error:
            self._write(
                stage,
                status="FAILURE",
                failure_reason=f"{type(error).__name__}: {error}",
            )
            raise
        else:
            self._write(
                stage,
                status=stage.completion_status,
                failure_reason=stage.completion_reason,
            )

    def _write(
        self,
        stage: PipelineStage,
        *,
        status: str,
        failure_reason: str | None,
    ) -> None:
        duration_ms = round((time.perf_counter() - stage.started_counter) * 1000, 3)
        log_day = stage.started_at.astimezone(SEOUL).date().isoformat()
        payload = {
            "pipeline_started_at": stage.started_at.isoformat(),
            "collection_date": stage.collection_date.isoformat(),
            "pipeline_name": stage.pipeline_name,
            "status": status,
            "duration_ms": duration_ms,
            "failure_reason": failure_reason,
            "details": stage.details,
        }
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        target = self.log_dir / f"{log_day}.log"
        with self._lock, target.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded)
            handle.write("\n")
