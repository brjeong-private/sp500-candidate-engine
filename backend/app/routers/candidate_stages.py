from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request

from backend.app.dependencies import get_database, require_api_key
from backend.app.repositories.candidate_stage_runs import CandidateStageConflict
from backend.app.schemas.candidate_stages import (
    CandidateStageAccepted,
    CandidateStageRequest,
    CandidateStageRun,
)
from backend.app.services.candidate_stages import CandidateStageService
from sp500_candidate_engine.database import Database

router = APIRouter(
    prefix="/api/v1/candidate-stage-runs", tags=["Independent candidate stages"],
    dependencies=[Depends(require_api_key)],
)
IdempotencyKey = Annotated[
    str, Header(alias="Idempotency-Key", min_length=1, max_length=128,
                pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"),
]


def get_stage_service(
    request: Request, database: Annotated[Database, Depends(get_database)],
) -> CandidateStageService:
    service = getattr(request.app.state, "candidate_stage_service", None)
    if service is not None:
        return service
    return CandidateStageService(database, request.app.state.engine_settings)


@router.post("", response_model=CandidateStageAccepted, status_code=202)
def create_stage(
    payload: CandidateStageRequest, background_tasks: BackgroundTasks,
    service: Annotated[CandidateStageService, Depends(get_stage_service)],
    idempotency_key: IdempotencyKey,
) -> CandidateStageAccepted:
    try:
        accepted = service.accept(payload, idempotency_key)
    except CandidateStageConflict as error:
        raise HTTPException(409, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    if not accepted._is_replay:
        background_tasks.add_task(service.execute_background, accepted.stage_run_id)
    return accepted


@router.get("/{stage_run_id}", response_model=CandidateStageRun)
def get_stage(
    stage_run_id: UUID,
    service: Annotated[CandidateStageService, Depends(get_stage_service)],
) -> CandidateStageRun:
    try:
        return service.get(stage_run_id)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error


@router.post("/{stage_run_id}/retry", response_model=CandidateStageAccepted, status_code=202)
def retry_stage(
    stage_run_id: UUID, background_tasks: BackgroundTasks,
    service: Annotated[CandidateStageService, Depends(get_stage_service)],
    idempotency_key: IdempotencyKey,
) -> CandidateStageAccepted:
    try:
        accepted = service.retry(stage_run_id, idempotency_key)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except CandidateStageConflict as error:
        raise HTTPException(409, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    if not accepted._is_replay:
        background_tasks.add_task(service.execute_background, accepted.stage_run_id)
    return accepted
