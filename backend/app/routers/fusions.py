from __future__ import annotations

from datetime import date as Date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from backend.app.dependencies import get_database
from backend.app.repositories.fusions import FusionReadRepository
from backend.app.schemas.common import Page
from backend.app.schemas.explanations import FusionExplanations, FusionRunWithReasons
from backend.app.schemas.fusions import FusionRun
from sp500_candidate_engine.database import Database

router = APIRouter(prefix="/api/v1/fusion-selections", tags=["Fusion selections"])
explanations_router = APIRouter(prefix="/api/v2/fusion-selections", tags=["Fusion explanations"])


@explanations_router.get("/{run_id}/explanations", response_model=FusionExplanations)
def get_explanations(
    run_id: UUID, database: Annotated[Database, Depends(get_database)],
) -> FusionExplanations:
    return FusionReadRepository(database).explanations(run_id)


@explanations_router.get("", response_model=Page[FusionRunWithReasons])
def list_fusions_with_reasons(
    database: Annotated[Database, Depends(get_database)],
    date: Date | None = None, start_date: Date | None = None, end_date: Date | None = None,
    model_purpose: Literal["MEDIUM_20D"] = "MEDIUM_20D",
    quant_selection_run_id: UUID | None = None,
    policy_version: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    config_hash: Annotated[str | None, Query(pattern="^[0-9a-f]{64}$")] = None,
    cursor: Annotated[str | None, Query(max_length=4096)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> Page[FusionRunWithReasons]:
    repository = FusionReadRepository(database)
    page = repository.list_runs(
        exact_date=date, start_date=start_date, end_date=end_date,
        quant_selection_run_id=quant_selection_run_id, cursor=cursor, limit=limit,
        policy_version=policy_version, config_hash=config_hash,
    )
    return Page[FusionRunWithReasons](
        items=[repository.with_reasons(run) for run in page.items],
        next_cursor=page.next_cursor,
    )


@explanations_router.get("/{run_id}", response_model=FusionRunWithReasons)
def get_fusion_with_reasons(
    run_id: UUID, database: Annotated[Database, Depends(get_database)],
) -> FusionRunWithReasons:
    repository = FusionReadRepository(database)
    return repository.with_reasons(repository.get_run(run_id))


@router.get("", response_model=Page[FusionRun])
def list_fusions(
    database: Annotated[Database, Depends(get_database)],
    date: Date | None = None, start_date: Date | None = None, end_date: Date | None = None,
    model_purpose: Literal["MEDIUM_20D"] = "MEDIUM_20D",
    quant_selection_run_id: UUID | None = None,
    policy_version: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    config_hash: Annotated[str | None, Query(pattern="^[0-9a-f]{64}$")] = None,
    cursor: Annotated[str | None, Query(max_length=4096)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> Page[FusionRun]:
    return FusionReadRepository(database).list_runs(
        exact_date=date, start_date=start_date, end_date=end_date,
        quant_selection_run_id=quant_selection_run_id, cursor=cursor, limit=limit,
        policy_version=policy_version, config_hash=config_hash,
    )


@router.get("/{run_id}", response_model=FusionRun)
def get_fusion(
    run_id: UUID, database: Annotated[Database, Depends(get_database)],
) -> FusionRun:
    return FusionReadRepository(database).get_run(run_id)


@router.get("/{run_id}/handoff")
def get_fusion_handoff(
    run_id: UUID, database: Annotated[Database, Depends(get_database)],
) -> dict[str, object]:
    return FusionReadRepository(database).handoff(run_id)
