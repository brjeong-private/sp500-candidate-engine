from datetime import date
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Request

from backend.app.dependencies import get_database, require_api_key
from backend.app.schemas.execution import (
    PipelineRunAccepted,
    PipelineRunRequest,
    PipelineSessionEligibility,
)
from backend.app.services.pipeline_execution import PipelineConflict, PipelineExecutionService
from sp500_candidate_engine.database import Database

router = APIRouter(prefix="/api/v1", tags=["pipeline execution"])


def get_execution_service(
    request: Request, database: Annotated[Database, Depends(get_database)]
) -> PipelineExecutionService:
    service = getattr(request.app.state, "execution_service", None)
    if service is not None:
        return service
    return PipelineExecutionService(database, request.app.state.engine_settings)


@router.get(
    "/pipeline-runs/eligibility",
    response_model=PipelineSessionEligibility,
    dependencies=[Depends(require_api_key)],
)
def get_pipeline_session_eligibility(
    target_date: Annotated[date, Query(alias="date")],
    service: Annotated[PipelineExecutionService, Depends(get_execution_service)],
) -> PipelineSessionEligibility:
    is_session, data_complete = service.session_eligibility(target_date)
    return PipelineSessionEligibility(
        date=target_date,
        is_session=is_session,
        data_complete=data_complete,
    )


@router.post(
    "/pipeline-runs",
    status_code=202,
    response_model=PipelineRunAccepted,
    dependencies=[Depends(require_api_key)],
)
def create_pipeline_run(
    payload: PipelineRunRequest,
    background_tasks: BackgroundTasks,
    service: Annotated[PipelineExecutionService, Depends(get_execution_service)],
    idempotency_key: Annotated[
        str,
        Header(
            alias="Idempotency-Key",
            min_length=1,
            max_length=128,
            pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
        ),
    ],
) -> PipelineRunAccepted:
    try:
        accepted = service.accept(payload, idempotency_key)
    except PipelineConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if not accepted._is_replay:
        background_tasks.add_task(service.execute_background, accepted.process_run_id)
    return accepted
