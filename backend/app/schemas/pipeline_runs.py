from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from backend.app.schemas.common import ReadModel
from backend.app.schemas.common import UTCDateTime as datetime

ProcessStatus = Literal["PENDING", "RUNNING", "SUCCEEDED", "PARTIAL_SUCCESS", "FAILED"]
ProcessType = Literal["DAILY", "RANGE", "BACKFILL", "BACKFILL_RETRY"]


class PipelineRun(ReadModel):
    process_run_id: UUID
    parent_process_run_id: UUID | None = None
    process_type: ProcessType
    status: ProcessStatus
    range_start: date
    range_end: date
    total_dates: int
    completed_dates: int
    success_dates: int
    failed_dates: int
    retry_required_dates: int
    retry_attempted_dates: int
    started_at: datetime
    heartbeat_at: datetime
    finished_at: datetime | None
    failure_reason: str | None = None


class CollectedCounts(ReadModel):
    daily_bars: int = 0
    corporate_actions: int = 0
    news: int = 0
    sec_filings: int = 0
    sec_facts: int = 0
    earnings: int = 0
    universe_members: int = 0
    exchange_sessions: int = 0
    changed_bars: int = 0
    missing_bars: int = 0
    changed_actions: int = 0
    events: int = 0
    changed_events: int = 0
    changed_filings: int = 0
    changed_facts: int = 0


class ProcessDateStatus(ReadModel):
    process_run_id: UUID
    collection_date: date
    attempt_no: int
    event_type: Literal["COLLECTION", "RETRY"]
    status: Literal["PENDING", "RUNNING", "SUCCEEDED", "FAILED"]
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: Decimal | None
    collected_item_count: int
    collected_counts: CollectedCounts
    failure_reason: str | None
    retry_required: bool
    retry_status: Literal["NOT_REQUIRED", "PENDING", "RUNNING", "SUCCEEDED", "FAILED"]
    completed: bool
    updated_at: datetime
