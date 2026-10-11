from __future__ import annotations

from datetime import date as Date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from backend.app.dependencies import get_database
from backend.app.repositories.candidates import CandidateRepository
from backend.app.schemas.candidates import Candidate
from backend.app.schemas.common import Page
from sp500_candidate_engine.database import Database

router = APIRouter(prefix="/api/v1/candidates", tags=["Candidates"])


@router.get("", response_model=Page[Candidate])
def list_candidates(
    database: Annotated[Database, Depends(get_database)],
    date: Date | None = None,
    start_date: Date | None = None,
    end_date: Date | None = None,
    selection_run_id: UUID | None = None,
    model_purpose: Literal["MEDIUM_20D", "SHORT_5D"] = "MEDIUM_20D",
    ticker: Annotated[str | None, Query(min_length=1, max_length=32)] = None,
    instrument_id: UUID | None = None,
    issuer_id: UUID | None = None,
    cursor: Annotated[str | None, Query(max_length=4096)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> Page[Candidate]:
    """All dates, newest first; each date defaults to its latest successful run.

    Explicit selection_run_id permits inspecting non-successful runs. Symbols and
    sectors come from the scoring run's historical universe, not today's universe.
    """
    return CandidateRepository(database).list_candidates(
        exact_date=date,
        start_date=start_date,
        end_date=end_date,
        selection_run_id=selection_run_id,
        model_purpose=model_purpose,
        ticker=ticker,
        instrument_id=instrument_id,
        issuer_id=issuer_id,
        cursor=cursor,
        limit=limit,
    )
