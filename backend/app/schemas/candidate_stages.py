from __future__ import annotations

from datetime import date
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator

from backend.app.schemas.common import ReadModel
from backend.app.schemas.common import UTCDateTime as datetime

Stage = Literal["QUANTITATIVE", "LLM_PRESELECTION", "FUSION"]
StageStatus = Literal["PENDING", "RUNNING", "SUCCEEDED", "SHORTFALL", "FAILED"]


class CandidateStageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: Stage
    target_session: date
    execution_context_id: UUID
    model_purpose: Literal["SHORT_5D", "MEDIUM_20D"] | None = None
    quant_selection_run_id: UUID | None = None
    llm_preselection_run_id: UUID | None = None

    @model_validator(mode="after")
    def stage_contract(self) -> Self:
        if self.stage == "FUSION":
            if self.model_purpose not in {None, "MEDIUM_20D"}:
                raise ValueError("Fusion supports MEDIUM_20D only")
            if self.quant_selection_run_id is None or self.llm_preselection_run_id is None:
                raise ValueError("Fusion requires both source selection run IDs")
            self.model_purpose = "MEDIUM_20D"
        else:
            if self.quant_selection_run_id is not None or self.llm_preselection_run_id is not None:
                raise ValueError("Only Fusion accepts source selection run IDs")
            if self.stage == "QUANTITATIVE":
                self.model_purpose = self.model_purpose or "MEDIUM_20D"
            elif self.model_purpose is not None:
                raise ValueError("Independent LLM does not accept a Quant model purpose")
        return self


class CandidateStageAccepted(ReadModel):
    stage_run_id: UUID
    status: StageStatus
    status_url: str
    _is_replay: bool = PrivateAttr(default=False)


class CandidateStageResult(ReadModel):
    selection_run_id: UUID | None = None
    scoring_run_id: UUID | None = None
    model_version_id: UUID | None = None
    llm_ranking_run_id: UUID | None = None
    fusion_run_id: UUID | None = None
    candidate_count: int = Field(ge=0, le=20)
    reused: bool


class CandidateStageRun(ReadModel):
    stage_run_id: UUID
    stage: Stage
    target_session: date
    execution_context_id: UUID
    model_purpose: Literal["SHORT_5D", "MEDIUM_20D"] | None
    retry_of_run_id: UUID | None
    status: StageStatus
    contract_hash: str
    input_hash: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    failure_code: str | None
    result: CandidateStageResult | None
