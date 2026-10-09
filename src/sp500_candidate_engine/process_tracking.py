from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from psycopg import Connection

from sp500_candidate_engine.database import Database
from sp500_candidate_engine.models import UTC


class ProcessLogWriter:
    _lock = threading.Lock()

    def __init__(self, log_dir: Path, process_run_id: uuid.UUID) -> None:
        self.path = (log_dir / "processes" / f"{process_run_id}.jsonl").resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        with self._lock, self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())


@dataclass(frozen=True)
class AttemptHandle:
    process_run_id: uuid.UUID
    collection_date: date
    attempt_no: int
    event_type: str
    started_at: datetime
    started_counter: float


class ProcessTracker:
    def __init__(self, database: Database) -> None:
        self.database = database
        self._connection_context: Any = None
        self.connection: Connection[dict[str, object]] | None = None

    def __enter__(self) -> ProcessTracker:
        self._connection_context = self.database.connect(autocommit=True)
        self.connection = self._connection_context.__enter__()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self._connection_context is not None:
            self._connection_context.__exit__(exc_type, exc, traceback)
        self.connection = None

    def create_run(
        self,
        *,
        process_run_id: uuid.UUID,
        process_type: str,
        range_start: date,
        range_end: date,
        total_dates: int,
        log_uri: str,
        metadata: dict[str, object],
    ) -> uuid.UUID:
        connection = self._require_connection()
        now = datetime.now(UTC)
        connection.execute(
            """
            INSERT INTO ops.process_run(
                process_run_id, process_type, status, range_start, range_end,
                total_dates, started_at, heartbeat_at, log_uri, metadata
            )
            VALUES (%s, %s, 'RUNNING', %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                process_run_id,
                process_type,
                range_start,
                range_end,
                total_dates,
                now,
                now,
                log_uri,
                json.dumps(metadata),
            ),
        )
        return process_run_id

    def start_attempt(
        self,
        process_run_id: uuid.UUID,
        collection_date: date,
        *,
        event_type: str,
    ) -> AttemptHandle:
        connection = self._require_connection()
        row = connection.execute(
            """
            SELECT COALESCE(max(attempt_no), 0) + 1 AS attempt_no
            FROM ops.process_date_status
            WHERE process_run_id = %s AND collection_date = %s
            """,
            (process_run_id, collection_date),
        ).fetchone()
        assert row is not None
        attempt_no = int(row["attempt_no"])
        now = datetime.now(UTC)
        connection.execute(
            """
            INSERT INTO ops.process_date_status(
                process_run_id, collection_date, attempt_no, event_type,
                status, started_at, retry_status
            )
            VALUES (
                %s, %s, %s, %s, 'RUNNING', %s,
                CASE WHEN %s = 'RETRY' THEN 'RUNNING' ELSE 'NOT_REQUIRED' END
            )
            """,
            (
                process_run_id,
                collection_date,
                attempt_no,
                event_type,
                now,
                event_type,
            ),
        )
        self.heartbeat(process_run_id)
        return AttemptHandle(
            process_run_id=process_run_id,
            collection_date=collection_date,
            attempt_no=attempt_no,
            event_type=event_type,
            started_at=now,
            started_counter=time.perf_counter(),
        )

    def finish_attempt(
        self,
        handle: AttemptHandle,
        *,
        success: bool,
        collected_counts: dict[str, int],
        failure_reason: str | None,
    ) -> dict[str, object]:
        connection = self._require_connection()
        finished_at = datetime.now(UTC)
        duration_ms = round((time.perf_counter() - handle.started_counter) * 1000, 3)
        collected_item_count = sum(
            value for key, value in collected_counts.items() if not key.startswith("missing")
        )
        retry_required = not success
        retry_status = (
            "PENDING"
            if retry_required
            else ("SUCCEEDED" if handle.event_type == "RETRY" else "NOT_REQUIRED")
        )
        connection.execute(
            """
            UPDATE ops.process_date_status
               SET status = %s,
                   finished_at = %s,
                   duration_ms = %s,
                   collected_item_count = %s,
                   collected_counts = %s,
                   failure_reason = %s,
                   retry_required = %s,
                   retry_status = %s,
                   completed = true,
                   updated_at = now()
             WHERE process_run_id = %s
               AND collection_date = %s
               AND attempt_no = %s
            """,
            (
                "SUCCEEDED" if success else "FAILED",
                finished_at,
                duration_ms,
                collected_item_count,
                json.dumps(collected_counts),
                failure_reason,
                retry_required,
                retry_status,
                handle.process_run_id,
                handle.collection_date,
                handle.attempt_no,
            ),
        )
        progress = self.refresh_aggregates(handle.process_run_id)
        return {
            "process_run_id": str(handle.process_run_id),
            "event_type": handle.event_type,
            "pipeline_started_at": handle.started_at.isoformat(),
            "collection_date": handle.collection_date.isoformat(),
            "duration_ms": duration_ms,
            "collected_item_count": collected_item_count,
            "collected_count": collected_item_count,
            "collected_counts": collected_counts,
            "status": "SUCCESS" if success else "FAILURE",
            "failure_reason": failure_reason,
            "retry_required": retry_required,
            "retry_status": retry_status,
            "completed": True,
            "progress": progress,
        }

    def dates_for_retry(
        self,
        process_run_id: uuid.UUID,
        *,
        start_date: date,
        end_date: date,
    ) -> tuple[date, ...]:
        rows = (
            self._require_connection()
            .execute(
                """
            SELECT collection_date
            FROM (
                SELECT DISTINCT ON (collection_date)
                    collection_date,
                    status
                FROM ops.process_date_status
                WHERE process_run_id = %s
                  AND collection_date BETWEEN %s AND %s
                ORDER BY collection_date, attempt_no DESC
            ) latest
            WHERE status = 'FAILED'
            ORDER BY collection_date
            """,
                (process_run_id, start_date, end_date),
            )
            .fetchall()
        )
        return tuple(row["collection_date"] for row in rows)

    def recover_stale_attempts(
        self,
        process_run_id: uuid.UUID,
        *,
        stale_after: timedelta = timedelta(minutes=5),
    ) -> int:
        stale_before = datetime.now(UTC) - stale_after
        updated = (
            self._require_connection()
            .execute(
                """
            UPDATE ops.process_date_status
               SET status = 'FAILED',
                   finished_at = now(),
                   failure_reason = 'Recovered stale RUNNING attempt after interruption',
                   retry_required = true,
                   retry_status = 'PENDING',
                   completed = true,
                   updated_at = now()
             WHERE process_run_id = %s
               AND status = 'RUNNING'
               AND started_at < %s
            """,
                (process_run_id, stale_before),
            )
            .rowcount
        )
        if updated:
            self.refresh_aggregates(process_run_id)
        return updated

    def refresh_aggregates(self, process_run_id: uuid.UUID) -> dict[str, int]:
        connection = self._require_connection()
        row = connection.execute(
            """
            WITH latest AS (
                SELECT DISTINCT ON (collection_date)
                    collection_date,
                    status,
                    retry_required
                FROM ops.process_date_status
                WHERE process_run_id = %s
                ORDER BY collection_date, attempt_no DESC
            ),
            retried AS (
                SELECT count(DISTINCT collection_date) AS count
                FROM ops.process_date_status
                WHERE process_run_id = %s AND event_type = 'RETRY'
            )
            SELECT
                count(*) AS completed_dates,
                count(*) FILTER (WHERE status = 'SUCCEEDED') AS success_dates,
                count(*) FILTER (WHERE status = 'FAILED') AS failed_dates,
                count(*) FILTER (WHERE retry_required) AS retry_required_dates,
                (SELECT count FROM retried) AS retry_attempted_dates
            FROM latest
            """,
            (process_run_id, process_run_id),
        ).fetchone()
        assert row is not None
        progress = {key: int(value) for key, value in row.items()}
        connection.execute(
            """
            UPDATE ops.process_run
               SET completed_dates = %s,
                   success_dates = %s,
                   failed_dates = %s,
                   retry_required_dates = %s,
                   retry_attempted_dates = %s,
                   heartbeat_at = now()
             WHERE process_run_id = %s
            """,
            (
                progress["completed_dates"],
                progress["success_dates"],
                progress["failed_dates"],
                progress["retry_required_dates"],
                progress["retry_attempted_dates"],
                process_run_id,
            ),
        )
        return progress

    def heartbeat(self, process_run_id: uuid.UUID) -> None:
        self._require_connection().execute(
            "UPDATE ops.process_run SET heartbeat_at = now() WHERE process_run_id = %s",
            (process_run_id,),
        )

    def finalize(self, process_run_id: uuid.UUID) -> dict[str, object]:
        connection = self._require_connection()
        progress = self.refresh_aggregates(process_run_id)
        total_row = connection.execute(
            "SELECT total_dates FROM ops.process_run WHERE process_run_id = %s",
            (process_run_id,),
        ).fetchone()
        assert total_row is not None
        total = int(total_row["total_dates"])
        if progress["success_dates"] == total:
            status = "SUCCEEDED"
        elif progress["success_dates"] > 0:
            status = "PARTIAL_SUCCESS"
        else:
            status = "FAILED"
        connection.execute(
            """
            UPDATE ops.process_run
               SET status = %s,
                   heartbeat_at = now(),
                   finished_at = now()
             WHERE process_run_id = %s
            """,
            (status, process_run_id),
        )
        return {"status": status, "total_dates": total, **progress}

    def get_status(self, process_run_id: uuid.UUID) -> dict[str, object]:
        connection = self._require_connection()
        row = connection.execute(
            "SELECT * FROM ops.process_run WHERE process_run_id = %s",
            (process_run_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"Unknown process_run_id: {process_run_id}")
        date_rows = connection.execute(
            """
            SELECT DISTINCT ON (collection_date)
                collection_date,
                attempt_no,
                event_type,
                status,
                started_at,
                finished_at,
                duration_ms,
                collected_item_count,
                collected_counts,
                failure_reason,
                retry_required,
                retry_status,
                completed
            FROM ops.process_date_status
            WHERE process_run_id = %s
            ORDER BY collection_date, attempt_no DESC
            """,
            (process_run_id,),
        ).fetchall()
        result = dict(row)
        result["dates"] = [dict(date_row) for date_row in date_rows]
        return result

    def _require_connection(self) -> Connection[dict[str, object]]:
        if self.connection is None:
            raise RuntimeError("ProcessTracker must be used as a context manager")
        return self.connection

    def active_connection(self) -> Connection[dict[str, object]]:
        return self._require_connection()
