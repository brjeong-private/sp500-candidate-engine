from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from backend.app.dependencies import get_database, require_api_key
from backend.app.schemas.weekly_training import (
    ActivationSmokeResult,
    WeeklyEligibility,
    WeeklyExecutionBinding,
    WeeklyTrainingAccepted,
    WeeklyTrainingRequest,
    WeeklyTrainingStatus,
)
from backend.app.services.weekly_training import (
    WeeklyTrainingConflict,
    WeeklyTrainingNotEligible,
    WeeklyTrainingNotFound,
    WeeklyTrainingService,
)
from sp500_candidate_engine.database import Database

router = APIRouter(
    prefix="/api/v1/pipeline-runs/weekly",
    tags=["weekly training"],
    dependencies=[Depends(require_api_key)],
)


def get_weekly_training_service(
    request: Request,
    database: Annotated[Database, Depends(get_database)],
) -> WeeklyTrainingService:
    service = getattr(request.app.state, "weekly_training_service", None)
    return service if service is not None else WeeklyTrainingService(database)


@router.get("/eligibility", response_model=WeeklyEligibility)
def weekly_eligibility(
    service: Annotated[WeeklyTrainingService, Depends(get_weekly_training_service)],
) -> WeeklyEligibility:
    return service.eligibility()


@router.post("", status_code=202, response_model=WeeklyTrainingAccepted)
def create_weekly_training(
    payload: WeeklyTrainingRequest,
    service: Annotated[WeeklyTrainingService, Depends(get_weekly_training_service)],
    idempotency_key: Annotated[
        str,
        Header(
            alias="Idempotency-Key",
            min_length=1,
            max_length=128,
            pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
        ),
    ],
) -> WeeklyTrainingAccepted:
    try:
        return service.accept(
            model_purpose=payload.model_purpose,
            idempotency_key=idempotency_key,
        )
    except WeeklyTrainingNotEligible as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/{weekly_run_id}", response_model=WeeklyTrainingStatus)
def get_weekly_training(
    weekly_run_id: UUID,
    service: Annotated[WeeklyTrainingService, Depends(get_weekly_training_service)],
) -> WeeklyTrainingStatus:
    try:
        return service.get(weekly_run_id)
    except WeeklyTrainingNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/{weekly_run_id}/execution", response_model=WeeklyTrainingStatus)
def bind_weekly_execution(
    weekly_run_id: UUID,
    payload: WeeklyExecutionBinding,
    service: Annotated[WeeklyTrainingService, Depends(get_weekly_training_service)],
) -> WeeklyTrainingStatus:
    try:
        return service.bind_execution(
            weekly_run_id,
            execution_name=payload.execution_name,
        )
    except WeeklyTrainingNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except WeeklyTrainingConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/{weekly_run_id}/activation-smoke", response_model=ActivationSmokeResult)
def activation_smoke(
    weekly_run_id: UUID,
    service: Annotated[WeeklyTrainingService, Depends(get_weekly_training_service)],
) -> ActivationSmokeResult:
    try:
        return service.activation_smoke(weekly_run_id)
    except WeeklyTrainingNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except WeeklyTrainingConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
