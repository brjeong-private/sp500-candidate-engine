from __future__ import annotations

from datetime import date as Date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from backend.app.dependencies import get_database
from backend.app.repositories.pipeline_runs import PipelineRunRepository
from backend.app.schemas.common import Page
from backend.app.schemas.pipeline_runs import (
    PipelineRun,
    ProcessDateStatus,
    ProcessStatus,
    ProcessType,
)
from sp500_candidate_engine.database import Database

router = APIRouter(prefix="/api/v1/pipeline-runs", tags=["Pipeline runs"])


@router.get("", response_model=Page[PipelineRun])
def list_pipeline_runs(
    database: Annotated[Database, Depends(get_database)],
    date: Date | None = None,
    start_date: Date | None = None,
    end_date: Date | None = None,
    status: ProcessStatus | None = None,
    process_type: ProcessType | None = None,
    cursor: Annotated[str | None, Query(max_length=4096)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> Page[PipelineRun]:
    """Filter runs by overlapping inclusive execution range.

    API-owned status overrides the engine collection status, including model and
    candidate failures. No request payloads, raw errors or filesystem log paths
    are public. Child runs include parent_process_run_id.
    """
    return PipelineRunRepository(database).list_runs(
        exact_date=date,
        start_date=start_date,
        end_date=end_date,
        status=status,
        process_type=process_type,
        cursor=cursor,
        limit=limit,
    )


@router.get("/{process_run_id}", response_model=PipelineRun)
def get_pipeline_run(
    process_run_id: UUID,
    database: Annotated[Database, Depends(get_database)],
) -> PipelineRun:
    return PipelineRunRepository(database).get_run(process_run_id)


@router.get("/{process_run_id}/dates", response_model=Page[ProcessDateStatus])
def list_pipeline_dates(
    process_run_id: UUID,
    database: Annotated[Database, Depends(get_database)],
    cursor: Annotated[str | None, Query(max_length=4096)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> Page[ProcessDateStatus]:
    """All attempts, including RANGE children; process_run_id identifies the child."""
    return PipelineRunRepository(database).list_dates(
        process_run_id,
        cursor=cursor,
        limit=limit,
    )
