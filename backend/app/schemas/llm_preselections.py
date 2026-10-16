from __future__ import annotations

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import Field

from backend.app.schemas.common import ReadModel
from backend.app.schemas.common import UTCDateTime as datetime


class LLMPreselectionEvidence(ReadModel):
    evidence_link_id: UUID
    source_snapshot_id: UUID
    source_kind: str
    entity_key: str
    source_available_at: datetime
    observed_at: datetime | None
    event_at: datetime | None
    priority: int


class LLMPreselectionCandidate(ReadModel):
    run_id: UUID
    instrument_id: UUID
    position: int
    score: float
    first_stage_rank: int
    final_rank: int
    evidence_quality: Literal["HIGH", "MEDIUM", "LOW"]
    reason_codes: list[str]
    symbol: str
    company_name: str
    sector: str | None
    evidence: list[LLMPreselectionEvidence] = Field(default_factory=list)


class LLMPreselection(ReadModel):
    run_id: UUID
    llm_ranking_run_id: UUID
    execution_context_id: UUID
    price_session_date: date
    cutoff_at: datetime
    generated_at: datetime
    valid_until: datetime | None
    policy_version: str
    prompt_version: str
    deployment: str
    evidence_schema_version: str
    requested_count: int
    selected_count: int
    status: Literal["SUCCEEDED", "SHORTFALL", "FAILED"]
    ranking_status: str
    failure_code: str | None
    created_at: datetime
    candidates: list[LLMPreselectionCandidate]
