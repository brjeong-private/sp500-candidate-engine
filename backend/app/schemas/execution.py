from __future__ import annotations

from datetime import date as Date
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, PrivateAttr, StrictBool, model_validator


class PipelineRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["DAILY", "RANGE", "BACKFILL"]
    date: Date | None = None
    start_date: Date | None = None
    end_date: Date | None = None
    with_candidates: StrictBool | None = None
    auto_retry: StrictBool | None = None
    model_purpose: Literal["SHORT_5D", "MEDIUM_20D"] | None = None

    @model_validator(mode="after")
    def validate_mode(self) -> Self:
        if self.mode == "DAILY":
            if self.date is None or self.start_date is not None or self.end_date is not None:
                raise ValueError("DAILY requires date and forbids start_date/end_date")
            if self.with_candidates is not True or self.auto_retry is not None:
                raise ValueError("DAILY requires with_candidates=true and forbids auto_retry")
            if self.model_purpose is None:
                self.model_purpose = "SHORT_5D"
        else:
            if self.model_purpose is not None:
                raise ValueError("model_purpose is allowed only for DAILY")
            if self.date is not None or self.start_date is None or self.end_date is None:
                raise ValueError("RANGE/BACKFILL require start_date/end_date and forbid date")
            if self.start_date > self.end_date:
                raise ValueError("start_date must be on or before end_date")
            if self.mode == "RANGE":
                if self.with_candidates is not False or self.auto_retry is not None:
                    raise ValueError("RANGE requires with_candidates=false and forbids auto_retry")
            elif self.with_candidates is not None:
                raise ValueError("BACKFILL forbids with_candidates")
        return self


class PipelineRunAccepted(BaseModel):
    process_run_id: UUID
    status: Literal["PENDING"] = "PENDING"
    status_url: str
    _is_replay: bool = PrivateAttr(default=False)


class PipelineSessionEligibility(BaseModel):
    date: Date
    exchange_mic: Literal["XNYS"] = "XNYS"
    is_session: bool
    data_complete: bool
