from datetime import UTC, date, datetime

import pytest

from sp500_candidate_engine.llm_preselection.asof import NEW_YORK, llm_cutoff, publication_bound
from sp500_candidate_engine.models import KnowledgeMode, RunSpec
from sp500_candidate_engine.temporal import TemporalFence

CUTOFF = datetime(2026, 10, 17, 9, 30, tzinfo=UTC)


@pytest.mark.parametrize(
    "value",
    [
        "2026-10-16",
        date(2026, 10, 16),
        "2026-10-16T23:59:59-04:00",
        "2026-10-17T00:30:00+00:00",
    ],
)
def test_previous_ny_days_accept_day_precision_without_a_creation_time(value):
    bound = publication_bound(value, CUTOFF)
    assert bound.local_date == date(2026, 10, 16)
    assert bound.precision == "DAY"
    assert bound.upper_bound_at.astimezone(NEW_YORK).hour == 23


def test_current_day_accepts_only_precise_times_before_0530():
    bound = publication_bound("2026-10-17T05:29:59-04:00", CUTOFF)
    assert bound.precision == "TIMESTAMP"
    assert bound.local_date == date(2026, 10, 17)


@pytest.mark.parametrize(
    "value",
    [
        "2026-10-17",
        "2026-10-17T05:30:00-04:00",
        "2026-10-17T05:30:01-04:00",
        "2026-10-18",
        "2026-10-17T04:00:00",
    ],
)
def test_current_day_missing_late_or_naive_times_and_future_days_are_rejected(value):
    with pytest.raises(ValueError):
        publication_bound(value, CUTOFF)


def test_winter_uses_new_york_est_not_fixed_utc_offset():
    cutoff = datetime(2026, 12, 17, 10, 30, tzinfo=UTC)
    assert publication_bound("2026-12-17T09:45:00+00:00", cutoff).precision == "TIMESTAMP"
    with pytest.raises(ValueError):
        publication_bound("2026-10-17T09:45:00+00:00", CUTOFF)


def test_explicit_context_cutoff_is_never_extended():
    earlier = datetime(2026, 10, 17, 8, 30, tzinfo=UTC)
    assert llm_cutoff(earlier) == earlier
    with pytest.raises(ValueError):
        publication_bound("2026-10-17T04:45:00-04:00", earlier)


def test_rule_does_not_change_collection_or_quant_fence():
    spec = RunSpec(date(2026, 10, 16), CUTOFF, KnowledgeMode.OPERATIONAL_REPLAY)
    fence = TemporalFence(spec)
    fence.require_source_available(CUTOFF)
    with pytest.raises(TypeError):
        fence.require_source_available(date(2026, 10, 16))
