from __future__ import annotations

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from backend.app.schemas.common import UTCDateTime

ModelPurpose = Literal["SHORT_5D", "MEDIUM_20D"]
WeeklyStatus = Literal[
    "PENDING",
    "RUNNING",
    "EVALUATED",
    "PROMOTED",
    "REJECTED",
    "ROLLED_BACK",
    "FAILED",
]


class WeeklyTrainingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_purpose: ModelPurpose


class WeeklyEligibility(BaseModel):
    eligible: bool
    iso_week: str | None = None
    anchor_session: date | None = None
    input_manifest_id: UUID | None = None
    training_cutoff: UTCDateTime | None = None
    label_maturity_cutoff: date | None = None
    reason: Literal["READY", "NO_COMPLETE_MANIFEST", "ALREADY_ACCEPTED"] | None = None


class WeeklyTrainingAccepted(BaseModel):
    weekly_run_id: UUID
    model_purpose: ModelPurpose
    status: WeeklyStatus
    status_url: str


class WeeklyExecutionBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    execution_name: str


class WeeklyTrainingStatus(BaseModel):
    weekly_run_id: UUID
    iso_week: str
    anchor_session: date
    model_purpose: ModelPurpose
    policy_version: str
    input_manifest_id: UUID
    training_cutoff: UTCDateTime
    label_maturity_cutoff: date
    status: WeeklyStatus
    container_job_execution_name: str | None = None
    export_run_id: UUID | None = None
    challenger_model_version_id: UUID | None = None
    champion_model_version_id: UUID | None = None
    error_code: str | None = None


class ActivationSmokeResult(BaseModel):
    weekly_run_id: UUID
    model_purpose: ModelPurpose
    passed: bool
