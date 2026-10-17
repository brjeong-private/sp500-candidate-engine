import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock
from uuid import UUID

import httpx
import pytest

from sp500_candidate_engine.analytics.azure_openai import AzureOpenAIResponse
from sp500_candidate_engine.llm_preselection.config import RateLimits, load_llm_preselection_config
from sp500_candidate_engine.llm_preselection.event_ranker import EventPreselectionRanker
from sp500_candidate_engine.llm_preselection.evidence import (
    EvidenceLink,
    EvidencePacket,
    EvidencePacketBuilder,
)
from sp500_candidate_engine.llm_preselection.ranker import (
    CachedCompletion,
    LlmRankerSettings,
    LlmRankingError,
)
from sp500_candidate_engine.llm_preselection.rate_limits import LlmRateLimiter
from sp500_candidate_engine.llm_preselection.screening import screen_packets

CUTOFF = datetime(2026, 10, 15, 9, 30, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[2]


def packet(index, *, event=True, available=None, event_at=None, kind="NEWS", issuer=None):
    instrument = UUID(int=index)
    link = EvidenceLink(
        UUID(int=index + 10000), UUID(int=index + 20000), kind, str(index),
        available or CUTOFF - timedelta(days=1), CUTOFF - timedelta(days=1), event_at,
    )
    return EvidencePacket(
        instrument, UUID(int=issuer or index), f"T{index}", f"Company {index}", "Tech",
        {"identity": {"instrument_id": str(instrument)}, "news": [{"title": "Earnings update"}]},
        str(index), 20, {"news": int(event)}, (), (), (link,) if event else (),
    )


def config():
    return load_llm_preselection_config(
        ROOT / "config" / "llm_preselection" / "policy_event_v2.yaml"
    )


def screen(packets):
    return screen_packets(
        packets, execution_context_id=UUID(int=999), cutoff_at=CUTOFF,
        policy_version=config().policy_version, config=config().screening,
    )


def test_event_config_is_distinct_and_non_price():
    assert config().event_policy
    assert config().windows.price_sessions == 0
    assert config().rubric == {
        "earnings": 25, "business": 25, "event": 20, "financial": 15, "industry": 15,
    }
    assert not load_llm_preselection_config(
        ROOT / "config" / "llm_preselection" / "policy_v1.yaml"
    ).event_policy


def test_event_packet_budget_trims_oldest_evidence_and_its_links_explicitly():
    repository = MagicMock()
    repository.read_events.side_effect = lambda **kwargs: (
        [{
            "event_revision_id": UUID(int=index + 100), "title": f"News {index}",
            "published_at": CUTOFF - timedelta(hours=index),
            "source_available_at": CUTOFF - timedelta(hours=index),
            "observed_at": CUTOFF - timedelta(hours=index),
            "source_snapshot_id": UUID(int=500),
            "metadata": {"description": "D" * 1000, "insights": ["X" * 1000] * 20},
        } for index in range(1, 31)]
        if kwargs["event_type"] == "NEWS" else []
    )
    repository.read_sec_filings.return_value = []
    repository.read_sec_facts.return_value = []
    repository.read_corporate_actions.return_value = []
    member = {
        "instrument_id": UUID(int=1), "issuer_id": UUID(int=2), "symbol": "TEST",
        "security_name": "Test Company", "sector": "Technology",
        "instrument_status": "LISTED", "universe_version_id": UUID(int=3),
        "universe_snapshot_id": UUID(int=4), "universe_source_available_at": CUTOFF,
        "instrument_state_id": UUID(int=5), "state_snapshot_id": UUID(int=6),
        "source_available_at": CUTOFF, "observed_at": CUTOFF,
    }
    packet = EvidencePacketBuilder(repository, config())._build_one(
        execution_context_id=UUID(int=999), target_session=CUTOFF.date(),
        cutoff_at=CUTOFF, member=member, bars=[],
    )
    encoded = json.dumps(packet.packet, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    assert len(encoded) <= config().limits.packet_characters
    assert "news" in packet.truncated_sections
    assert 0 < packet.section_counts["news"] < 30
    assert packet.packet["news"][0]["title"] == "News 1"
    assert len([link for link in packet.links if link.source_kind == "NEWS"]) \
        == packet.section_counts["news"]


def test_screening_budget_controls_and_determinism():
    packets = tuple(packet(index) for index in range(1, 111)) + tuple(
        packet(index, event=False) for index in range(111, 131)
    )
    first, second = screen(packets), screen(tuple(reversed(packets)))
    assert len(first.packets) == 100
    assert sum(row["selected"] and row["screening_group"] == "EVENT" for row in first.audit) == 90
    assert sum(row["selected"] and row["screening_group"] == "CONTROL" for row in first.audit) == 10
    assert first == second


def test_quotas_do_not_transfer_or_force_padding():
    result = screen(tuple(packet(index, event=False) for index in range(1, 51)))
    assert len(result.packets) == 10


def test_seven_day_boundary_and_future_known_earnings():
    result = screen((
        packet(1, available=CUTOFF - timedelta(days=7)),
        packet(2, available=CUTOFF - timedelta(days=7) + timedelta(microseconds=1)),
        packet(3, kind="EARNINGS", available=CUTOFF - timedelta(days=30),
               event_at=CUTOFF + timedelta(days=7)),
    ))
    scores = {row["instrument_id"]: row["screening_event_score"] for row in result.audit}
    assert [scores[str(UUID(int=index))] for index in range(1, 4)] == [0, 1, 1]


def test_screening_rejects_future_evidence_instead_of_making_it_a_control():
    with pytest.raises(ValueError, match="cutoff"):
        screen((packet(4, available=CUTOFF + timedelta(seconds=1)),))


def test_issuer_representative_does_not_depend_on_quant_score():
    result = screen((packet(2, issuer=1), packet(1, issuer=1)))
    assert len(result.packets) == 1
    assert result.packets[0].instrument_id == UUID(int=1)


class Client:
    def __init__(self, supported=3, invalid=False):
        self.supported = supported
        self.invalid = invalid
        self.calls = []

    async def complete(self, *, messages, schema_name, schema):
        self.calls.append(schema_name)
        rows = json.loads(messages[1]["content"])
        output = []
        for row in rows:
            criteria = ["earnings", "business", "event", "financial", "industry"]
            scores = dict(zip(criteria, [75, 80, 70, 65, 75], strict=True))
            supported = criteria[:self.supported]
            value = {
                "instrument_id": row["instrument_id"],
                "scores": {key: score if key in supported else None
                           for key, score in scores.items()},
                "missing_reasons": {key: None if key in supported else "No supplied evidence"
                                    for key in criteria},
                "evidence_quality": "MEDIUM", "uncertainty": "HIGH", "summary": "Supplied news.",
                "evidence": [
                    {"criterion": key, "evidence_link_id": row["evidence"][0]["evidence_link_id"],
                     "reason": "Reported change in supplied news"}
                    for key in supported
                ],
            }
            if self.invalid:
                value["evidence"][0]["evidence_link_id"] = str(UUID(int=999999))
            output.append(value)
        return AzureOpenAIResponse({"assessments": output}, 10, 5, 15)


def rank(client):
    ranker = EventPreselectionRanker(
        LlmRankerSettings("https://example.openai.azure.com", "test", "test"),
        config(), client=client,
    )
    return asyncio.run(ranker.rank(
        llm_ranking_run_id=UUID(int=999),
        packets=tuple(packet(index) for index in range(1, 21)),
    ))


@pytest.mark.parametrize("supported,expected", [(3, 75.3571), (4, 73.5294), (5, 73.75)])
def test_normalized_scoring_and_no_second_stage(supported, expected):
    client = Client(supported)
    result = rank(client)
    assert len(result.candidates) == 20
    assert result.assessments[0].score == expected
    assert result.assessments[0].supported_count == supported
    assert client.calls == ["event_assessments_v2"] * 4
    assert result.attempts[0].response_output is not None


def test_insufficient_evidence_is_explicit_and_not_neutral_score():
    result = rank(Client(2))
    assert not result.candidates
    assert all(item.score is None and item.reason_codes == ("INSUFFICIENT_EVIDENCE",)
               for item in result.assessments)


def test_foreign_evidence_fails_entire_run():
    with pytest.raises(LlmRankingError, match="malformed"):
        rank(Client(invalid=True))


def test_schema_binds_citations_to_each_instrument_instead_of_batch_union():
    ranker = EventPreselectionRanker(
        LlmRankerSettings("https://example.openai.azure.com", "test", "test"),
        config(), client=Client(),
    )
    packets = [packet(1), packet(2)]
    variants = ranker._assessment_schema(packets)["properties"]["assessments"]["items"]["anyOf"]
    assert len(variants) == 2
    for variant, item in zip(variants, packets, strict=True):
        properties = variant["properties"]
        assert properties["instrument_id"]["enum"] == [str(item.instrument_id)]
        assert properties["evidence"]["items"]["properties"]["evidence_link_id"]["enum"] == [
            str(item.links[0].evidence_link_id)
        ]


def test_semantic_repair_is_bounded_and_records_distinct_attempt_numbers():
    class RepairClient(Client):
        async def complete(self, **kwargs):
            self.invalid = not self.calls
            return await super().complete(**kwargs)

    result = rank(RepairClient())
    assert len(result.candidates) == 20
    assert result.attempts[0].status == "FAILED"
    assert result.attempts[0].error_code == "OUTPUT_VALIDATION_FAILED"
    assert result.attempts[1].status == "SUCCEEDED"
    assert [attempt.attempt_no for attempt in result.attempts[:2]] == [1, 2]


def test_valid_citations_for_unscored_criteria_do_not_increase_coverage_or_score():
    class LimitationClient(Client):
        async def complete(self, **kwargs):
            response = await super().complete(**kwargs)
            for assessment in response.output["assessments"]:
                citation = assessment["evidence"][0]
                assessment["evidence"].append({
                    **citation, "criterion": "industry",
                    "reason": "This supplied source does not establish an industry outlook.",
                })
            return response

    complete = rank(LimitationClient(supported=3))
    assert len(complete.candidates) == 20
    assert complete.assessments[0].score == 75.3571
    assert complete.assessments[0].supported_count == 3
    assert complete.assessments[0].weight_denominator == 70
    assert complete.assessments[0].sub_scores["industry"] is None
    assert complete.assessments[0].missing_reasons["industry"]
    insufficient = rank(LimitationClient(supported=2))
    assert not insufficient.candidates
    assert all(item.score is None and item.supported_count == 2
               for item in insufficient.assessments)


def test_failed_cached_response_cannot_exhaust_repair_without_a_new_call():
    packets = tuple(replace(
        packet(index), packet={
            **packet(index).packet, "execution_context_id": str(UUID(int=999))
        },
    ) for index in range(1, 21))
    settings = LlmRankerSettings("https://example.openai.azure.com", "test", "test")
    invalid = EventPreselectionRanker(
        settings, replace(config(), max_attempts=1), client=Client(invalid=True),
    )
    with pytest.raises(LlmRankingError) as failed:
        asyncio.run(invalid.rank(llm_ranking_run_id=UUID(int=1000), packets=packets))
    original = failed.value.attempts[0]
    cache = {original.input_hash: CachedCompletion(
        original.response_output, original.output_hash, original.call_attempt_id
    )}
    client = Client()
    retry = EventPreselectionRanker(settings, config(), client=client)
    cache_modes = []

    def cached(input_hash, context_id, include_failed):
        cache_modes.append(include_failed)
        return cache.get(input_hash) if include_failed else None

    retry.response_cache = cached
    result = asyncio.run(retry.rank(llm_ranking_run_id=UUID(int=2000), packets=packets))
    assert len(result.candidates) == 20
    assert cache_modes[:2] == [True, False]
    assert len(client.calls) == 4
    assert result.attempts[0].cache_source_attempt_id is not None
    assert result.attempts[0].error_code == "OUTPUT_VALIDATION_FAILED"
    assert result.attempts[1].http_status == 200


def test_rate_limits_wait_for_both_rpm_and_tpm_without_real_sleep():
    clock = [0.0]
    delays = []

    async def sleep(seconds):
        delays.append(seconds)
        clock[0] += seconds

    limiter = LlmRateLimiter(RateLimits(2, 100, 10), clock=lambda: clock[0], sleep=sleep)

    async def run():
        await limiter.acquire(30)
        limiter.record_usage(50)
        await limiter.acquire(30)
        await limiter.acquire(30)

    asyncio.run(run())
    assert delays == [60]
    with pytest.raises(ValueError, match="TPM"):
        asyncio.run(limiter.acquire(100))


def test_cached_responses_keep_stable_citations_but_remap_database_links():
    packets = tuple(
        replace(packet(index), packet={
            **packet(index).packet, "execution_context_id": str(UUID(int=999))
        }) for index in range(1, 21)
    )
    first_client = Client()
    first = EventPreselectionRanker(
        LlmRankerSettings("https://example.openai.azure.com", "test", "test"),
        config(), client=first_client,
    )
    initial = asyncio.run(first.rank(llm_ranking_run_id=UUID(int=1000), packets=packets))
    cache = {
        attempt.input_hash: CachedCompletion(
            attempt.response_output, attempt.output_hash, attempt.call_attempt_id
        ) for attempt in initial.attempts
    }
    remapped = tuple(replace(
        item, links=tuple(replace(
            link, citation_id=link.evidence_link_id,
            evidence_link_id=UUID(int=link.evidence_link_id.int + 1000000),
        ) for link in item.links)
    ) for item in packets)
    second_client = Client(invalid=True)
    second = EventPreselectionRanker(
        LlmRankerSettings("https://example.openai.azure.com", "test", "test"),
        config(), client=second_client,
    )
    second.response_cache = lambda input_hash, context_id, include_failed: cache.get(input_hash)
    cached = asyncio.run(second.rank(llm_ranking_run_id=UUID(int=2000), packets=remapped))
    assert not second_client.calls
    assert len(cached.candidates) == 20
    assert all(attempt.total_tokens == 0 and attempt.cache_source_attempt_id
               for attempt in cached.attempts)
    assert cached.candidates[0].evidence_ids == (remapped[0].links[0].evidence_link_id,)


def test_partial_successful_batches_are_reused_after_a_later_call_fails():
    class FailingClient(Client):
        async def complete(self, **kwargs):
            if self.calls:
                raise httpx.ReadTimeout("simulated")
            return await super().complete(**kwargs)

    packets = tuple(replace(
        packet(index), packet={
            **packet(index).packet, "execution_context_id": str(UUID(int=999))
        }
    ) for index in range(1, 21))
    first = EventPreselectionRanker(
        LlmRankerSettings("https://example.openai.azure.com", "test", "test"),
        replace(config(), max_attempts=1), client=FailingClient(),
    )
    with pytest.raises(LlmRankingError) as failed:
        asyncio.run(first.rank(llm_ranking_run_id=UUID(int=1000), packets=packets))
    cache = {
        item.input_hash: CachedCompletion(
            item.response_output, item.output_hash, item.call_attempt_id
        )
        for item in failed.value.attempts if item.status == "SUCCEEDED"
    }
    client = Client()
    retry = EventPreselectionRanker(
        LlmRankerSettings("https://example.openai.azure.com", "test", "test"),
        config(), client=client,
    )
    retry.response_cache = lambda input_hash, context_id, include_failed: cache.get(input_hash)
    result = asyncio.run(retry.rank(llm_ranking_run_id=UUID(int=2000), packets=packets))
    assert len(result.candidates) == 20
    assert len(client.calls) == 3
