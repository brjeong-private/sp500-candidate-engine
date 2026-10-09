from __future__ import annotations

from datetime import date, datetime

from sp500_candidate_engine.models import KnowledgeMode, RunSpec


class FutureDataViolation(ValueError):
    """Raised when a collection run observes data outside its temporal boundary."""


class TemporalFence:
    def __init__(self, run_spec: RunSpec) -> None:
        self.run_spec = run_spec

    def require_session_date(self, value: date, *, field: str = "session_date") -> None:
        if value > self.run_spec.target_date:
            raise FutureDataViolation(
                f"{field}={value.isoformat()} exceeds target_date="
                f"{self.run_spec.target_date.isoformat()}"
            )

    def require_source_available(
        self, value: datetime, *, field: str = "source_available_at"
    ) -> None:
        if value > self.run_spec.cutoff_at:
            raise FutureDataViolation(
                f"{field}={value.isoformat()} exceeds cutoff_at="
                f"{self.run_spec.cutoff_at.isoformat()}"
            )

    def require_observed(self, value: datetime, *, field: str = "observed_at") -> None:
        if (
            self.run_spec.knowledge_mode is KnowledgeMode.OPERATIONAL_REPLAY
            and value > self.run_spec.cutoff_at
        ):
            raise FutureDataViolation(
                f"{field}={value.isoformat()} exceeds operational cutoff_at="
                f"{self.run_spec.cutoff_at.isoformat()}"
            )

    def validate_record(
        self,
        *,
        session_date: date,
        source_available_at: datetime,
        observed_at: datetime,
    ) -> None:
        self.require_session_date(session_date)
        self.require_source_available(source_available_at)
        self.require_observed(observed_at)
