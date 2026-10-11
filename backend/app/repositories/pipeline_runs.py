from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from fastapi import HTTPException

from backend.app.pagination import date_filters, decode_cursor, encode_cursor, page_limit
from backend.app.repositories.base import ReadRepository
from backend.app.schemas.common import Page
from backend.app.schemas.pipeline_runs import (
    PipelineRun,
    ProcessDateStatus,
    ProcessStatus,
    ProcessType,
)

_RUN_SELECT = """
    p.process_run_id, p.parent_process_run_id, p.process_type,
    COALESCE(r.status, p.status) AS status, p.range_start, p.range_end,
    p.total_dates, p.completed_dates, p.success_dates, p.failed_dates,
    p.retry_required_dates, p.retry_attempted_dates, p.started_at, p.heartbeat_at,
    CASE WHEN r.process_run_id IS NOT NULL THEN r.finished_at
        ELSE p.finished_at END AS finished_at,
    CASE WHEN COALESCE(r.status, p.status) IN ('FAILED', 'PARTIAL_SUCCESS')
        THEN 'One or more pipeline stages failed; consult operational logs.'
        ELSE NULL END AS failure_reason
"""
_RUN_TABLES = """
    ops.process_run p
    LEFT JOIN ops.backend_pipeline_request r USING (process_run_id)
"""
_COUNT_KEYS = {
    "daily_bars": ("daily_bars", "bars"),
    "corporate_actions": ("corporate_actions", "actions"),
    "news": ("news",),
    "sec_filings": ("sec_filings", "filings"),
    "sec_facts": ("sec_facts", "facts"),
    "earnings": ("earnings",),
    "universe_members": ("universe_members",),
    "exchange_sessions": ("exchange_sessions",),
    "changed_bars": ("changed_bars",),
    "missing_bars": ("missing_bars",),
    "changed_actions": ("changed_actions",),
    "events": ("events",),
    "changed_events": ("changed_events",),
    "changed_filings": ("changed_filings",),
    "changed_facts": ("changed_facts",),
}


class PipelineRunRepository(ReadRepository):
    def list_runs(
        self,
        *,
        exact_date: date | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        status: ProcessStatus | None = None,
        process_type: ProcessType | None = None,
        cursor: str | None = None,
        limit: int = 100,
    ) -> Page[PipelineRun]:
        page_limit(limit)
        start_date, end_date = date_filters(exact_date, start_date, end_date)
        filters: dict[str, object] = {
            "start": start_date,
            "end": end_date,
            "status": status,
            "type": process_type,
        }
        position = decode_cursor(cursor, "pipeline-runs", filters, 2)
        clauses = []
        parameters: list[object] = []
        if start_date is not None:
            clauses.append("p.range_start <= %s AND p.range_end >= %s")
            parameters.extend([end_date, start_date])
        if status is not None:
            clauses.append("COALESCE(r.status, p.status) = %s")
            parameters.append(status)
        if process_type is not None:
            clauses.append("p.process_type = %s")
            parameters.append(process_type)
        if position is not None:
            try:
                timestamp = datetime.fromisoformat(position[0])
                identifier = UUID(position[1])
                if timestamp.tzinfo is None:
                    raise ValueError
            except ValueError:
                raise HTTPException(422, "Invalid pipeline cursor") from None
            clauses.append("(p.started_at, p.process_run_id) < (%s, %s)")
            parameters.extend([timestamp, identifier])
        parameters.append(limit + 1)
        rows = self.fetch(
            f"""
            SELECT {_RUN_SELECT} FROM {_RUN_TABLES}
            {"WHERE " + " AND ".join(clauses) if clauses else ""}
            ORDER BY p.started_at DESC, p.process_run_id DESC LIMIT %s
        """,
            parameters,
        )
        next_cursor = None
        if len(rows) > limit:
            last = rows[limit - 1]
            next_cursor = encode_cursor(
                "pipeline-runs", filters, [str(last["started_at"]), str(last["process_run_id"])]
            )
        return Page[PipelineRun](
            items=[PipelineRun.model_validate(row) for row in rows[:limit]],
            next_cursor=next_cursor,
        )

    def get_run(self, process_run_id: UUID) -> PipelineRun:
        rows = self.fetch(
            f"SELECT {_RUN_SELECT} FROM {_RUN_TABLES} WHERE p.process_run_id = %s",
            [process_run_id],
        )
        if not rows:
            raise HTTPException(404, "Pipeline run not found")
        return PipelineRun.model_validate(rows[0])

    def list_dates(
        self,
        process_run_id: UUID,
        *,
        cursor: str | None = None,
        limit: int = 100,
    ) -> Page[ProcessDateStatus]:
        page_limit(limit)
        self.get_run(process_run_id)
        filters: dict[str, object] = {"run": process_run_id}
        position = decode_cursor(cursor, "pipeline-dates", filters, 3)
        parameters: list[object] = [process_run_id, process_run_id]
        boundary = ""
        if position is not None:
            try:
                boundary_date = date.fromisoformat(position[0])
                attempt_no = int(position[1])
                identifier = UUID(position[2])
            except ValueError:
                raise HTTPException(422, "Invalid pipeline dates cursor") from None
            boundary = """
                AND (d.collection_date < %s OR (d.collection_date = %s
                    AND (d.attempt_no, d.process_run_id) > (%s, %s)))
            """
            parameters.extend([boundary_date, boundary_date, attempt_no, identifier])
        parameters.append(limit + 1)
        counts = []
        for public_key, source_keys in _COUNT_KEYS.items():
            values = ", ".join(f"d.collected_counts->'{key}'" for key in source_keys)
            counts.extend([f"'{public_key}'", f"COALESCE({values}, '0'::jsonb)"])
        rows = self.fetch(
            f"""
            SELECT d.process_run_id, d.collection_date, d.attempt_no, d.event_type,
                d.status, d.started_at, d.finished_at, d.duration_ms,
                d.collected_item_count,
                jsonb_build_object({", ".join(counts)}) AS collected_counts,
                CASE WHEN d.failure_reason IS NOT NULL THEN
                    'Collection attempt failed; consult operational logs.'
                    ELSE NULL END AS failure_reason,
                d.retry_required, d.retry_status, d.completed, d.updated_at
            FROM ops.process_date_status d
            JOIN ops.process_run p USING (process_run_id)
            WHERE (d.process_run_id = %s OR p.parent_process_run_id = %s) {boundary}
            ORDER BY d.collection_date DESC, d.attempt_no ASC, d.process_run_id ASC
            LIMIT %s
        """,
            parameters,
        )
        next_cursor = None
        if len(rows) > limit:
            last = rows[limit - 1]
            next_cursor = encode_cursor(
                "pipeline-dates",
                filters,
                [
                    str(last["collection_date"]),
                    str(last["attempt_no"]),
                    str(last["process_run_id"]),
                ],
            )
        return Page[ProcessDateStatus](
            items=[ProcessDateStatus.model_validate(row) for row in rows[:limit]],
            next_cursor=next_cursor,
        )
