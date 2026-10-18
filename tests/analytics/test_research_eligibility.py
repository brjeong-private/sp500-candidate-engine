import uuid
from datetime import UTC, date, datetime, timedelta

import pytest

from sp500_candidate_engine.analytics.research_eligibility import (
    CLASSIFICATION,
    POLICY_VERSION,
    read_research_members,
    research_members,
)
from sp500_candidate_engine.llm_preselection.evidence import EvidencePacketBuilder

DAY = date(2026, 9, 30)
CUTOFF = datetime(2026, 10, 1, 9, 30, tzinfo=UTC)


def example():
    member_ids = [uuid.uuid4(), uuid.uuid4()]
    universe_id = uuid.uuid4()
    snapshot_id = uuid.uuid4()
    members = [{
        "instrument_id": key, "issuer_id": uuid.uuid4(), "symbol": f"T{i}",
        "universe_version_id": universe_id, "universe_snapshot_id": snapshot_id,
        "universe_source_available_at": CUTOFF-timedelta(hours=12),
        "announced_at": CUTOFF-timedelta(hours=12), "effective_at": CUTOFF-timedelta(hours=12),
    } for i, key in enumerate(member_ids)]
    bars = [{
        "instrument_id": member_ids[0], "session_date": DAY,
        "source_available_at": CUTOFF-timedelta(hours=12), "volume": 100,
        "open": 10, "high": 11, "low": 9, "close": 10,
        "price_adjustment_status": "UNADJUSTED", "volume_adjustment_status": "UNADJUSTED",
    }]
    scope = {
        "research_eligibility": {
            "policy_version": POLICY_VERSION, "classification": CLASSIFICATION,
            "target_session": str(DAY), "official_historical_state_verified": False,
        },
        "original_current_instrument_ids": [str(key) for key in member_ids],
        "quarantined_current_instrument_ids": [str(member_ids[1])],
        "original_reference_count": 2, "universe_version_id": str(universe_id),
        "generated_at": "2026-10-18T07:00:00+00:00",
        "data_publication_max": (CUTOFF-timedelta(hours=12)).isoformat(),
    }
    return dict(
        members=members, bars=bars, scope=scope, target_session=DAY, cutoff_at=CUTOFF,
        snapshot_id=uuid.uuid4(),
    )


def test_research_does_not_manufacture_official_state_and_keeps_quarantine_audit():
    kwargs = example()
    rows = research_members(**kwargs)
    assert rows[0]["research_gate_reasons"] == ()
    assert rows[1]["research_gate_reasons"] == (
        "CERTIFIED_SCOPE_ISSUER_QUARANTINE", "MISSING_RESEARCH_TARGET_PRICE",
    )
    assert all(row["instrument_status"] is None for row in rows)
    assert all(row["official_historical_state_verified"] is False for row in rows)
    assert all("instrument_state_id" not in row for row in rows)
    assert all("instrument_status" not in row for row in kwargs["members"])
    links = EvidencePacketBuilder._links(rows[0], [], [], [], [], [], [])
    assert all(link.source_kind == "UNIVERSE" for link in links)
    assert any(link.entity_key.startswith(CLASSIFICATION) for link in links)
    assert all(link.source_available_at <= CUTOFF for link in links)


@pytest.mark.parametrize("failure", [
    "future_bar", "future_membership", "wrong_day", "quarantine_bar",
    "changed_membership", "later_cutoff", "missing_policy",
])
def test_research_never_relaxes_temporal_identity_or_quality(failure):
    kwargs = example()
    if failure == "future_bar":
        kwargs["bars"][0]["source_available_at"] = CUTOFF+timedelta(seconds=1)
    elif failure == "future_membership":
        kwargs["members"][0]["announced_at"] = CUTOFF+timedelta(seconds=1)
    elif failure == "wrong_day":
        kwargs["bars"][0]["session_date"] = DAY-timedelta(days=1)
    elif failure == "quarantine_bar":
        kwargs["bars"][0]["instrument_id"] = kwargs["members"][1]["instrument_id"]
    elif failure == "changed_membership":
        kwargs["members"].pop()
    elif failure == "later_cutoff":
        kwargs["cutoff_at"] += timedelta(days=1)
    else:
        del kwargs["scope"]["research_eligibility"]
    with pytest.raises(ValueError):
        research_members(**kwargs)


def test_unknown_adjustments_are_not_relabelled():
    kwargs = example()
    kwargs["bars"][0]["price_adjustment_status"] = "UNKNOWN"
    assert "INVALID_RESEARCH_TARGET_PRICE" in research_members(**kwargs)[0]["research_gate_reasons"]


def test_ordinary_context_is_not_given_research_fallback():
    from types import SimpleNamespace

    calls = []

    def execute(sql, params):
        calls.append((sql, params))
        return SimpleNamespace(fetchall=lambda: [])

    repository = SimpleNamespace(connection=SimpleNamespace(execute=execute))
    assert read_research_members(
        repository, execution_context_id=uuid.uuid4(), target_session=DAY,
    ) is None
    assert len(calls) == 1
    assert POLICY_VERSION in calls[0][1]


def test_research_tag_in_operational_replay_fails_closed():
    from types import SimpleNamespace

    repository = SimpleNamespace(connection=SimpleNamespace(execute=lambda *_: SimpleNamespace(
        fetchall=lambda: [{
            "knowledge_mode": "OPERATIONAL_REPLAY", "source_snapshot_id": uuid.uuid4(),
            "coverage_end": DAY,
        }],
    )))
    with pytest.raises(ValueError, match="DAILY reconstruction"):
        read_research_members(repository, execution_context_id=uuid.uuid4(), target_session=DAY)


@pytest.mark.parametrize("future", [False, True])
def test_explicit_reader_binds_scope_and_rejects_future_manifest(monkeypatch, future):
    from types import SimpleNamespace

    from sp500_candidate_engine.analytics import research_eligibility as module

    example_data = example()
    scope = example_data["scope"]
    monkeypatch.setattr(module, "read_scope_artifact", lambda **_: scope)
    queries = []
    rows = iter([
        [{
            "knowledge_mode": "HISTORICAL_RECONSTRUCTION", "cutoff_at": CUTOFF,
            "source_snapshot_id": example_data["snapshot_id"], "coverage_end": DAY,
            "source_available_at": datetime.fromisoformat(scope["data_publication_max"]),
            "storage_uri": "file:///verified-scope", "content_hash": "a" * 64,
        }],
        [{"source_snapshot_id": uuid.uuid4()}] if future else [],
        example_data["members"],
    ])

    def execute(sql, params):
        queries.append(sql)
        return SimpleNamespace(fetchall=lambda: next(rows))

    repository = SimpleNamespace(
        connection=SimpleNamespace(execute=execute),
        read_bars=lambda **_: example_data["bars"],
    )
    if future:
        with pytest.raises(ValueError, match="future source/coverage"):
            read_research_members(repository, execution_context_id=uuid.uuid4(), target_session=DAY)
    else:
        members = read_research_members(
            repository, execution_context_id=uuid.uuid4(), target_session=DAY,
        )
        assert members[0]["eligibility_policy"] == POLICY_VERSION
        assert "instrument_state" not in queries[-1]
