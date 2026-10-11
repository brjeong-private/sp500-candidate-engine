from __future__ import annotations

from datetime import date
from typing import Literal
from uuid import UUID

from backend.app.schemas.common import ReadModel
from backend.app.schemas.common import UTCDateTime as datetime


class CandidateReason(ReadModel):
    reason_code: str
    priority: int
    event_revision_id: UUID | None = None


class Candidate(ReadModel):
    selection_run_id: UUID
    selection_type: Literal["QUANTITATIVE"]
    price_session_date: date
    cutoff_at: datetime
    generated_at: datetime
    valid_until: datetime | None
    scoring_run_id: UUID
    model_version_id: UUID
    model_name: str
    model_version: str
    model_purpose: Literal["SHORT_5D", "MEDIUM_20D"]
    prediction_horizon_sessions: int
    return_policy: str
    promotion_status: Literal["SHADOW", "CHAMPION", "REJECTED", "ARCHIVED"]
    score_semantics: str
    policy_version: str
    status: Literal["RUNNING", "SUCCEEDED", "SHORTFALL", "FAILED"]
    selected_count: int
    requested_count: int
    instrument_id: UUID
    issuer_id: UUID
    ticker: str
    company_name: str
    sector: str | None
    position: int
    score: float
    predicted_return: float | None
    rank_overall: int
    score_percentile: float
    rank_sector: int | None
    quality_status: str
    latest_data_at: datetime
    reasons: list[CandidateReason]
