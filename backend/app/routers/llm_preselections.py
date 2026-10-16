from __future__ import annotations

from datetime import date as Date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from backend.app.dependencies import get_database
from backend.app.repositories.llm_preselections import LLMPreselectionRepository
from backend.app.schemas.common import Page
from backend.app.schemas.llm_preselections import LLMPreselection
from sp500_candidate_engine.database import Database

router = APIRouter(prefix="/api/v1/llm-preselections", tags=["LLM preselections"])


@router.get("", response_model=Page[LLMPreselection])
def list_llm_preselections(
    database: Annotated[Database, Depends(get_database)],
    date: Date | None = None,
    start_date: Date | None = None,
    end_date: Date | None = None,
    run_id: UUID | None = None,
    cursor: Annotated[str | None, Query(max_length=4096)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> Page[LLMPreselection]:
    """Return each date's latest successful, stored LLM preselection run."""
    return LLMPreselectionRepository(database).list_preselections(
        exact_date=date,
        start_date=start_date,
        end_date=end_date,
        run_id=run_id,
        cursor=cursor,
        limit=limit,
    )


@router.get("/{run_id}", response_model=LLMPreselection)
def get_llm_preselection(
    run_id: UUID,
    database: Annotated[Database, Depends(get_database)],
) -> LLMPreselection:
    """Inspect one run, including failed and shortfall runs."""
    return LLMPreselectionRepository(database).get_preselection(run_id)
