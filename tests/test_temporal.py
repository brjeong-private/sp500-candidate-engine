from datetime import date, datetime

import pytest

from sp500_candidate_engine.models import UTC, KnowledgeMode, RunSpec
from sp500_candidate_engine.temporal import FutureDataViolation, TemporalFence


def test_rejects_session_after_target_date() -> None:
    fence = TemporalFence(
        RunSpec.for_date(date(2026, 10, 1), KnowledgeMode.HISTORICAL_RECONSTRUCTION)
    )
    with pytest.raises(FutureDataViolation):
        fence.require_session_date(date(2026, 10, 2))


def test_reconstruction_allows_late_observation() -> None:
    run_spec = RunSpec.for_date(date(2026, 10, 1), KnowledgeMode.HISTORICAL_RECONSTRUCTION)
    fence = TemporalFence(run_spec)
    fence.validate_record(
        session_date=date(2026, 10, 1),
        source_available_at=datetime(2026, 10, 1, 20, 15, tzinfo=UTC),
        observed_at=datetime(2026, 10, 9, 9, 0, tzinfo=UTC),
    )


def test_operational_replay_rejects_late_observation() -> None:
    run_spec = RunSpec.for_date(date(2026, 10, 1), KnowledgeMode.OPERATIONAL_REPLAY)
    fence = TemporalFence(run_spec)
    with pytest.raises(FutureDataViolation):
        fence.validate_record(
            session_date=date(2026, 10, 1),
            source_available_at=datetime(2026, 10, 1, 20, 15, tzinfo=UTC),
            observed_at=datetime(2026, 10, 9, 9, 0, tzinfo=UTC),
        )
