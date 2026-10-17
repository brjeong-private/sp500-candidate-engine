from __future__ import annotations

from datetime import date
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from backend.app.schemas.common import ReadModel, UTCDateTime
from backend.app.schemas.candidates import Candidate
from backend.app.schemas.fusions import FusionRun
from backend.app.schemas.llm_preselections import LLMPreselectionCandidate
from sp500_candidate_engine.fusion.explanations import CandidateExplanation


class CandidateExplanationView(ReadModel):
    instrument_id: UUID
    issuer_id: UUID
    position: int = Field(ge=1, le=20)
    status: Literal["RECORDED", "NOT_RECORDED"]
    explanation: CandidateExplanation | None

    @model_validator(mode="after")
    def validate_status(self) -> Self:
        if (self.status == "RECORDED") != (self.explanation is not None):
            raise ValueError("Explanation recording status mismatch")
        return self


class FusionExplanations(ReadModel):
    schema_version: Literal["candidate-explanation-v1", "candidate-explanation-v3"]
    fusion_run_id: UUID
    execution_context_id: UUID
    price_session_date: date
    cutoff_at: UTCDateTime
    selection_status: Literal["SUCCEEDED", "SHORTFALL", "FAILED"]
    failure_code: str | None
    status: Literal["RECORDED", "NOT_RECORDED"]
    candidates: list[CandidateExplanationView]


class LLMPreselectionWithReasons(LLMPreselectionCandidate):
    rationale: str
    uncertainty: Literal["LOW", "MEDIUM", "HIGH"]


class FusionSelectionReasons(CandidateExplanationView):
    source: Literal["STORED_SNAPSHOT", "PINNED_SOURCE_RESULTS"]
    quantitative: Candidate | None
    llm: LLMPreselectionWithReasons | None
    fusion_summary: str

    @model_validator(mode="after")
    def validate_source(self) -> Self:
        if (self.source == "STORED_SNAPSHOT") != (self.status == "RECORDED"):
            raise ValueError("Selection reason source does not match snapshot status")
        if any(
            candidate is not None and candidate.instrument_id != self.instrument_id
            for candidate in (self.quantitative, self.llm)
        ):
            raise ValueError("Selection reasons refer to another instrument")
        return self


class FusionRunWithReasons(FusionRun):
    selection_reasons: list[FusionSelectionReasons]

    @model_validator(mode="after")
    def validate_reason_candidates(self) -> Self:
        if [
            (item.instrument_id, item.issuer_id, item.position) for item in self.selection_reasons
        ] != [
            (item.instrument_id, item.issuer_id, item.position) for item in self.candidates
        ]:
            raise ValueError("Selection reasons must match the ordered final candidates")
        return self
