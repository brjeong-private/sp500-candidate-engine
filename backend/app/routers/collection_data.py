from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from backend.app.dependencies import get_database
from backend.app.repositories.collection_data import CollectionDataRepository
from backend.app.schemas.collection_data import CollectionRecord, Dataset
from backend.app.schemas.common import Page
from sp500_candidate_engine.database import Database

router = APIRouter(prefix="/api/v1/collection-data", tags=["Collection data"])


@router.get("/{dataset}", response_model=Page[CollectionRecord])
def list_collection_data(
    dataset: Dataset,
    database: Annotated[Database, Depends(get_database)],
    start_date: date,
    end_date: date,
    ticker: Annotated[str | None, Query(min_length=1, max_length=32)] = None,
    instrument_id: UUID | None = None,
    issuer_id: UUID | None = None,
    cursor: Annotated[str | None, Query(max_length=4096)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> Page[CollectionRecord]:
    """Normalized observations, not point-in-time model inputs (no manifest fence).

    Inclusive calendar range, at most 10 days. Semantic dates:
    daily-bars/exchange-sessions: session_date; corporate-actions: effective_date;
    news: published_at UTC date; earnings: scheduled_at UTC date;
    sec-filings: filed_date; sec-facts: source_available_at UTC date (not period_end);
    universe-members: version as_of_date (not each day of membership validity).
    Null news/earnings dates are excluded. Bars return latest revision per
    instrument/session/source; actions/events return latest logical revision.
    Issuer-level filings/facts are filtered via associated instruments without
    expanding or duplicating facts. Sessions reject entity filters.
    """
    return CollectionDataRepository(database).list_records(
        dataset,
        start_date=start_date,
        end_date=end_date,
        ticker=ticker,
        instrument_id=instrument_id,
        issuer_id=issuer_id,
        cursor=cursor,
        limit=limit,
    )
