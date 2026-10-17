import asyncio
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock
from uuid import UUID

import pytest

from sp500_candidate_engine.database import _canonical_hash
from sp500_candidate_engine.llm_preselection.repository import LlmPreselectionRepository

CONTEXT, SNAPSHOT, RUN = UUID(int=1000), UUID(int=1001), UUID(int=1002)
CUTOFF = datetime(2026, 10, 16, 9, 30, tzinfo=UTC)
TARGET = date(2026, 10, 15)


class Cursor:
    def __init__(self, value):
        self.value = value

    def fetchone(self):
        return self.value

    def fetchall(self):
        return self.value


class Connection:
    def __init__(self, results):
        self.results = iter(results)

    def execute(self, sql, params):
        assert sql.count("%s") == len(params)
        return Cursor(next(self.results))


def data():
    packets, links, audit = [], [], []
    for index in range(1, 21):
        instrument = UUID(int=index)
        payload = {
            "execution_context_id": str(CONTEXT), "target_session": TARGET.isoformat(),
            "cutoff_at": CUTOFF.isoformat(), "schema_version": "2",
            "identity": {"instrument_id": str(instrument), "issuer_id": str(UUID(int=100 + index)),
                         "symbol": f"T{index}", "company_name": f"Company {index}", "sector": None},
        }
        packets.append({
            "instrument_id": instrument, "packet": payload, "packet_hash": _canonical_hash(payload),
            "estimated_tokens": 30, "section_counts": {"news": 1},
            "missing_sections": [], "truncated_sections": [],
        })
        links.append({
            "instrument_id": instrument, "source_snapshot_id": SNAPSHOT, "source_kind": "NEWS",
            "entity_key": str(index), "source_available_at": CUTOFF - timedelta(days=1),
            "observed_at": CUTOFF - timedelta(hours=1), "event_at": CUTOFF - timedelta(days=1),
        })
        audit.append({"decision": {"instrument_id": str(instrument), "selected": True}})
    snapshots = [{
        "source_snapshot_id": SNAPSHOT, "source_available_at": CUTOFF + timedelta(days=1),
        "fetched_at": CUTOFF + timedelta(days=1),
    }]
    return [{"llm_ranking_run_id": RUN, "eligible_count": 20}, packets, links, snapshots, audit]


def load(results, mode="HISTORICAL_RECONSTRUCTION"):
    return LlmPreselectionRepository(Connection(results)).read_cached_inputs(
        execution_context_id=CONTEXT, target_session=TARGET, policy_hash="policy",
        schema_version="2", cutoff_at=CUTOFF, knowledge_mode=mode,
    )


def test_historical_cache_keeps_old_rows_in_later_reobserved_manifest_container():
    run_id, packets, audit = load(data())
    assert run_id == RUN and len(packets) == len(audit) == 20
    assert all(link.source_available_at <= CUTOFF for item in packets for link in item.links)


def test_operational_cache_rejects_later_observed_snapshot():
    with pytest.raises(ValueError, match="manifest/cutoff"):
        load(data(), mode="OPERATIONAL_REPLAY")


@pytest.mark.parametrize(
    "invalid", ["future_row", "outside_manifest", "hash", "screening", "count"]
)
def test_invalid_cache_is_not_silently_rebuilt(invalid):
    results = deepcopy(data())
    if invalid == "future_row":
        results[2][0]["source_available_at"] = CUTOFF + timedelta(seconds=1)
    elif invalid == "outside_manifest":
        results[3] = []
    elif invalid == "hash":
        results[1][0]["packet_hash"] = "invalid"
    elif invalid == "screening":
        results[4][0]["decision"]["selected"] = False
    else:
        results[1].pop()
    with pytest.raises(ValueError):
        load(results)


def test_fresh_and_cached_packet_order_produce_identical_success_identity(monkeypatch):
    from sp500_candidate_engine.llm_preselection import service as module
    from sp500_candidate_engine.llm_preselection.config import load_llm_preselection_config
    from sp500_candidate_engine.llm_preselection.ranker import LlmRankerSettings

    _, packets, decisions = load(data())
    source = MagicMock()
    source.read_context.return_value = {
        "cutoff_at": CUTOFF, "knowledge_mode": "HISTORICAL_RECONSTRUCTION",
    }
    monkeypatch.setattr(module, "SourceRepository", lambda _: source)
    builder = MagicMock()
    builder.build_all.return_value = tuple(reversed(packets))
    builder.screening_audit = decisions
    monkeypatch.setattr(module, "EvidencePacketBuilder", lambda *args: builder)
    repository = MagicMock()
    repository.read_cached_inputs.side_effect = [None, (RUN, packets, decisions)]
    repository.find_successful_run.return_value = {
        "llm_ranking_run_id": RUN, "run_id": UUID(int=2000), "selected_count": 20,
    }
    monkeypatch.setattr(module, "LlmPreselectionRepository", lambda _: repository)
    config = load_llm_preselection_config(
        Path(__file__).resolve().parents[2] / "config" / "llm_preselection" / "policy_event_v2.yaml"
    )
    service = module.LlmPreselectionService(
        MagicMock(), config,
        LlmRankerSettings("https://example.invalid", "test", "test"), ranker=MagicMock(),
    )
    first = asyncio.run(service._run(target_session=TARGET, execution_context_id=CONTEXT))
    second = asyncio.run(service._run(target_session=TARGET, execution_context_id=CONTEXT))
    hashes = [call.kwargs["input_hash"]
              for call in repository.find_successful_run.call_args_list]
    assert first.reused and second.reused
    assert hashes[0] == hashes[1]
    assert builder.build_all.call_count == 1
