from __future__ import annotations

import math
from datetime import date
from fractions import Fraction
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from backend.app.schemas.common import ReadModel
from backend.app.schemas.common import UTCDateTime as datetime


class FusionCandidate(ReadModel):
    instrument_id: UUID
    issuer_id: UUID
    ticker: str
    sector: str | None
    position: int = Field(ge=1, le=20)
    quant_rank: int | None = Field(default=None, ge=1, le=20)
    quant_rank_overall: int | None = None
    quant_predicted_return: float | None = Field(default=None, allow_inf_nan=False)
    llm_rank: int | None = Field(default=None, ge=1, le=20)
    llm_assessment_rank: int | None = None
    llm_score: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    rrf_score: float = Field(gt=0, allow_inf_nan=False)
    rrf_numerator: int = Field(gt=0)
    rrf_denominator: int = Field(gt=0)
    selected_by_quant: bool
    selected_by_llm: bool
    quality_status: Literal["OK"]
    risk_status: Literal["PASSED"]
    reason_codes: list[str]
    source_evidence_refs: list[UUID]

    @model_validator(mode="after")
    def validate_sources(self) -> Self:
        if (
            self.selected_by_quant != (self.quant_rank is not None)
            or self.selected_by_llm != (self.llm_rank is not None)
            or (self.quant_rank is None) != (self.quant_predicted_return is None)
            or (self.llm_rank is None) != (self.llm_score is None)
            or not (self.selected_by_quant or self.selected_by_llm)
        ):
            raise ValueError("Fusion source flags and scores do not match")
        return self


class FusionRun(ReadModel):
    fusion_run_id: UUID
    execution_context_id: UUID
    quant_selection_run_id: UUID | None
    llm_preselection_run_id: UUID | None
    price_session_date: date
    cutoff_at: datetime
    generated_at: datetime
    model_purpose: Literal["MEDIUM_20D"]
    selection_type: Literal["FUSION"]
    policy_version: str
    config_hash: str
    rrf_k: int = Field(gt=0)
    requested_count: Literal[20]
    selected_count: int = Field(ge=0, le=20)
    union_count: int = Field(ge=0, le=40)
    status: Literal["SUCCEEDED", "SHORTFALL", "FAILED"]
    failure_code: str | None
    sector_cap_relaxed: bool
    provenance: dict[str, object]
    payload_hash: str
    created_at: datetime
    candidates: list[FusionCandidate]

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        candidates = self.candidates
        if (
            len(candidates) != self.selected_count
            or [item.position for item in candidates] != list(range(1, len(candidates) + 1))
            or len({item.instrument_id for item in candidates}) != len(candidates)
            or len({item.issuer_id for item in candidates}) != len(candidates)
            or (self.status == "SUCCEEDED") != (self.selected_count == 20)
            or (self.status == "FAILED" and self.selected_count != 0)
            or (self.status == "SUCCEEDED" and (
                self.failure_code is not None or self.quant_selection_run_id is None
                or self.llm_preselection_run_id is None
            ))
            or (self.status != "SUCCEEDED" and self.failure_code is None)
        ):
            raise ValueError("Invalid Fusion run shape")
        ordered = []
        for item in candidates:
            score = sum(
                (Fraction(1, self.rrf_k + rank)
                 for rank in (item.quant_rank, item.llm_rank) if rank is not None),
                Fraction(0),
            )
            if score != Fraction(item.rrf_numerator, item.rrf_denominator) or not math.isclose(
                float(score), item.rrf_score, rel_tol=0, abs_tol=1e-15
            ):
                raise ValueError("Fusion score does not match source ranks")
            ordered.append((-score, item.instrument_id.hex))
        if ordered != sorted(ordered):
            raise ValueError("Fusion order is not deterministic")
        return self
