import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from sp500_candidate_engine.database import _canonical_hash
from sp500_candidate_engine.llm_preselection.config import load_llm_preselection_config
from sp500_candidate_engine.llm_preselection.event_ranker import EventPreselectionRanker
from sp500_candidate_engine.llm_preselection.evidence import EvidenceLink, EvidencePacket
from sp500_candidate_engine.llm_preselection.ranker import LlmRankerSettings
from sp500_candidate_engine.llm_preselection.temporal import validate_packet

CUTOFF = datetime(2026, 10, 15, 9, 30, tzinfo=UTC)
TARGET = date(2026, 10, 14)
CONTEXT = UUID(int=999)


def source_packet():
    payload = {
        "execution_context_id": str(CONTEXT),
        "target_session": TARGET.isoformat(),
        "cutoff_at": CUTOFF.isoformat(),
        "schema_version": "2",
        "identity": {"instrument_id": str(UUID(int=1)), "issuer_id": str(UUID(int=2))},
        "news": [
            {
                "event_revision_id": "news",
                "title": "Actual operating change",
                "published_at": (CUTOFF - timedelta(microseconds=1)).isoformat(),
            }
        ],
    }
    before = CUTOFF - timedelta(microseconds=1)
    link = EvidenceLink(UUID(int=3), UUID(int=4), "NEWS", "news", before, CUTOFF, before)
    return EvidencePacket(
        UUID(int=1),
        UUID(int=2),
        "TEST",
        "Test issuer",
        "Technology",
        payload,
        _canonical_hash(payload),
        10,
        {"news": 1},
        (),
        (),
        (link,),
    )


def check(packet, mode="HISTORICAL_RECONSTRUCTION"):
    validate_packet(
        packet,
        cutoff_at=CUTOFF,
        target_session=TARGET,
        execution_context_id=CONTEXT,
        knowledge_mode=mode,
    )


@pytest.mark.parametrize(
    "violation",
    [
        "source",
        "publication",
        "accepted",
        "period",
        "unlinked",
        "trimmed",
        "wrong_context",
        "wrong_session",
        "naive_cutoff",
        "hash",
        "screening",
    ],
)
def test_historical_fence_rejects_every_input_path(violation):
    packet = source_packet()
    payload = deepcopy(packet.packet)
    future = CUTOFF + timedelta(microseconds=1)
    if violation == "source":
        packet = replace(packet, links=(replace(packet.links[0], source_available_at=future),))
    elif violation in {"publication", "accepted"}:
        key = "published_at" if violation == "publication" else "accepted_at"
        payload["news"][0][key] = future.isoformat()
    elif violation == "period":
        payload["facts"] = [{"fact_id": "fact", "period_end": "2026-12-31"}]
        packet = replace(
            packet,
            links=(
                *packet.links,
                replace(packet.links[0], source_kind="SEC_FACT", entity_key="fact"),
            ),
        )
    elif violation == "unlinked":
        payload["news"].append({"event_revision_id": "unknown", "title": "Unlinked future payload"})
    elif violation == "trimmed":
        payload["news"] = []
    elif violation == "wrong_context":
        payload["execution_context_id"] = str(UUID(int=888))
    elif violation == "wrong_session":
        payload["target_session"] = "2026-10-15"
    elif violation == "naive_cutoff":
        payload["cutoff_at"] = "2026-10-15T09:30:00"
    elif violation == "screening":
        packet = replace(
            packet, screening_links=(replace(packet.links[0], source_available_at=future),)
        )
    packet = replace(packet, packet=payload, packet_hash=_canonical_hash(payload))
    if violation == "hash":
        packet = replace(packet, packet_hash="invalid")
    with pytest.raises(ValueError):
        check(packet)


def test_cutoff_not_midnight_is_the_boundary_and_known_schedule_is_allowed():
    packet = source_packet()
    check(packet, "OPERATIONAL_REPLAY")
    packet.packet["filings"] = [
        {
            "filing_id": "filing",
            "period_end": CUTOFF.date().isoformat(),
            "accepted_at": (CUTOFF - timedelta(microseconds=1)).isoformat(),
            "form_type": "8-K",
        }
    ]
    packet = replace(
        packet,
        packet_hash=_canonical_hash(packet.packet),
        links=(
            *packet.links,
            replace(packet.links[0], source_kind="SEC_FILING", entity_key="filing"),
        ),
    )
    check(packet, "OPERATIONAL_REPLAY")
    packet.packet["earnings"] = [
        {
            "event_revision_id": "schedule",
            "scheduled_at": (CUTOFF + timedelta(days=7)).isoformat(),
            "title": "Known earnings schedule",
        }
    ]
    packet = replace(
        packet,
        packet_hash=_canonical_hash(packet.packet),
        links=(
            *packet.links,
            replace(
                packet.links[0],
                source_kind="EARNINGS",
                entity_key="schedule",
                event_at=CUTOFF + timedelta(days=7),
            ),
        ),
    )
    check(packet, "OPERATIONAL_REPLAY")


def test_reconstruction_never_relaxes_public_availability_only_later_observation():
    packet = source_packet()
    later = CUTOFF + timedelta(days=20)
    packet = replace(packet, links=(replace(packet.links[0], observed_at=later),))
    check(packet, "HISTORICAL_RECONSTRUCTION")
    with pytest.raises(ValueError, match="observation"):
        check(packet, "OPERATIONAL_REPLAY")
    packet = replace(packet, links=(replace(packet.links[0], source_available_at=later),))
    with pytest.raises(ValueError, match="cutoff"):
        check(packet, "HISTORICAL_RECONSTRUCTION")


def test_invalid_input_cannot_call_llm_or_response_cache():
    packet = source_packet()
    packet = replace(
        packet,
        links=(replace(packet.links[0], source_available_at=CUTOFF + timedelta(microseconds=1)),),
    )
    config = load_llm_preselection_config(
        Path(__file__).parents[2] / "config" / "llm_preselection" / "policy_event_v2.yaml"
    )
    client = MagicMock(complete=AsyncMock())
    ranker = EventPreselectionRanker(
        LlmRankerSettings("https://fixture.invalid", "mock", "test"),
        config,
        client=client,
    )
    ranker.response_cache = MagicMock()
    with pytest.raises(ValueError, match="cutoff"):
        asyncio.run(ranker.rank(llm_ranking_run_id=UUID(int=1000), packets=(packet,)))
    client.complete.assert_not_awaited()
    ranker.response_cache.assert_not_called()


@pytest.mark.parametrize("limit", [1, 2, 3, 4, 600])
def test_citation_summary_respects_exact_character_budget(limit):
    from sp500_candidate_engine.llm_preselection.summaries import citation_summary

    citations = [{"criterion": "earnings", "reason": "Reported operating change " * 30}]
    assert len(citation_summary({"earnings": 80}, citations, limit=limit)) == limit
    assert len(citation_summary({}, [], limit=limit)) <= limit


@pytest.mark.parametrize("existing_revision", [False, True])
def test_late_corrected_news_cannot_inherit_its_original_publication_time(existing_revision):
    from sp500_candidate_engine.production_repository import ProductionRepository

    connection = MagicMock()
    connection.execute.return_value.fetchone.return_value = (
        {"event_revision_id": UUID(int=100), "revision_no": 1, "payload_hash": "old"}
        if existing_revision
        else None
    )
    published = CUTOFF - timedelta(days=1)
    observed = CUTOFF + timedelta(days=1)
    ProductionRepository._persist_event(
        connection,
        source_id=1,
        source_event_id="article",
        event_type="NEWS",
        canonical_key="NEWS:article",
        title="Corrected operating update",
        source_url="https://news.example.test/article",
        scheduled_at=None,
        published_at=published,
        source_available_at=published,
        observed_at=observed,
        snapshot_id=UUID(int=5),
        metadata={"title": "Updated"},
        symbols=(),
        instrument_ids={},
    )
    insert = next(
        call
        for call in connection.execute.call_args_list
        if "INSERT INTO event.event_revision(" in call.args[0]
    )
    assert insert.args[1][7] == (observed if existing_revision else published)
