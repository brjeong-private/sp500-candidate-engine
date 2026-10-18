import asyncio
import copy
import json
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest

from sp500_candidate_engine.analytics.azure_openai import AzureOpenAIClient, AzureOpenAIResponse
from sp500_candidate_engine.database import _canonical_hash
from sp500_candidate_engine.llm_preselection.config import load_llm_preselection_config
from sp500_candidate_engine.llm_preselection.enrichment_contract import (
    SEARCH_OMISSION_GAP,
    source_filing,
)
from sp500_candidate_engine.llm_preselection.event_ranker import EventPreselectionRanker
from sp500_candidate_engine.llm_preselection.evidence import EvidenceLink, EvidencePacket
from sp500_candidate_engine.llm_preselection.external_enrichment import (
    ExternalEvidenceError,
    LlmSearchEnricher,
    SearchProviderError,
)
from sp500_candidate_engine.llm_preselection.ranker import LlmRankerSettings
from sp500_candidate_engine.llm_preselection.temporal import validate_model_packets

ROOT = Path(__file__).parents[2]
CUTOFF = datetime(2026, 10, 15, 9, 30, tzinfo=UTC)
ACCEPTED = datetime(2026, 10, 14, 16, tzinfo=UTC)
DAY = date(2026, 10, 14)
ACCESSION = "0000000123-26-000001"
URL = f"https://www.sec.gov/Archives/edgar/data/123/{ACCESSION}.txt"
FILING = {
    "filing_id": str(UUID(int=6)),
    "accession_no": ACCESSION,
    "form_type": "8-K",
    "accepted_at": ACCEPTED.isoformat(),
    "filed_date": str(DAY),
    "period_end": str(DAY),
}


def config():
    return load_llm_preselection_config(
        ROOT / "config" / "llm_preselection" / "policy_event_search_v4.yaml"
    )


def packet():
    payload = {
        "schema_version": "4",
        "execution_context_id": str(UUID(int=1000)),
        "target_session": str(DAY),
        "cutoff_at": CUTOFF.isoformat(),
        "identity": {
            "instrument_id": str(UUID(int=1)),
            "issuer_id": str(UUID(int=2)),
            "cik": "123",
        },
        "news": [{"event_revision_id": "news", "title": "private-db-only"}],
        "filings": [copy.deepcopy(FILING)],
    }
    return EvidencePacket(
        UUID(int=1),
        UUID(int=2),
        "TEST",
        "Example Issuer",
        "Energy",
        payload,
        _canonical_hash(payload),
        20,
        {"news": 1, "filings": 1},
        (),
        (),
        (
            EvidenceLink(UUID(int=3), UUID(int=4), "NEWS", "news", ACCEPTED, ACCEPTED, ACCEPTED),
            EvidenceLink(
                UUID(int=5),
                UUID(int=4),
                "SEC_FILING",
                FILING["filing_id"],
                ACCEPTED,
                ACCEPTED,
                None,
            ),
        ),
    )


def response():
    text = "2026-10-14 | 과거 공시에서 제공된 사업 현황을 확인했습니다. [1]"
    start = text.index("[1]")
    return {
        "id": "resp_test",
        "status": "completed",
        "previous_response_id": None,
        "model": "search-model-2026-09-29",
        "output": [
            {
                "type": "web_search_call",
                "status": "completed",
                "action": {
                    "type": "search",
                    "queries": ["site:sec.gov past original"],
                    "sources": [{"type": "url", "url": URL}],
                },
            },
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": text,
                        "annotations": [
                            {
                                "type": "url_citation",
                                "url": URL,
                                "start_index": start,
                                "end_index": start + 3,
                            }
                        ],
                    }
                ],
            },
        ],
        "usage": {"total_tokens": 100},
    }


@pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 504, None, 401, 403, 400])
def test_provider_retries_only_transient_failures_and_retains_safe_audit(tmp_path, status):
    class Transient(SearchClient):
        attempts = 0

        async def search(self, **kwargs):
            self.attempts += 1
            if self.attempts == 1:
                request = httpx.Request("POST", self.endpoint)
                if status is None:
                    raise httpx.ReadTimeout("private diagnostic", request=request)
                failed = httpx.Response(
                    status, request=request, headers={"x-request-id": "request-1"},
                    json={"error": {"code": "ProviderError", "message": "private diagnostic"}},
                )
                failed.raise_for_status()
            return await super().search(**kwargs)

    client = Transient()
    enricher = LlmSearchEnricher(
        replace(config(), base_delay_seconds=0), artifact_directory=tmp_path, client=client,
    )

    async def execute():
        return await enricher._search(instructions="public", public_input={}, context_key="context")

    retryable = status not in (400, 401, 403)
    if retryable:
        assert asyncio.run(execute()) == response()
        assert client.attempts == 2
    else:
        with pytest.raises(SearchProviderError):
            asyncio.run(execute())
        assert client.attempts == 1
    artifacts = list(tmp_path.glob("*.json"))
    assert len(artifacts) == 1
    assert "private diagnostic" not in artifacts[0].read_text()
    audit = json.loads(artifacts[0].read_text())
    assert audit["http_status"] == status
    assert audit["retryable"] is retryable
    assert audit["provider_request_id"] == ("request-1" if status is not None else None)


def test_provider_exhausted_retries_remain_failure_not_omission(tmp_path):
    class Failed(SearchClient):
        attempts = 0

        async def search(self, **kwargs):
            self.attempts += 1
            httpx.Response(500, request=httpx.Request("POST", self.endpoint)).raise_for_status()

    client = Failed()
    policy = replace(optional_config(), base_delay_seconds=0)
    enricher = LlmSearchEnricher(policy, artifact_directory=tmp_path, client=client)
    with pytest.raises(SearchProviderError) as failure:
        asyncio.run(enricher.enrich((packet(),), knowledge_mode="HISTORICAL_RECONSTRUCTION"))
    assert client.attempts == policy.max_attempts
    assert failure.value.status == 500
    assert len(list(tmp_path.glob("*.json"))) == policy.max_attempts
    assert all(
        json.loads(path.read_text())["schema_version"] == "llm-search-provider-failure-v1"
        for path in tmp_path.glob("*.json")
    )


def test_parallel_search_is_bounded_ordered_and_reuses_completed_results(tmp_path):
    class Concurrent(SearchClient):
        active = peak = 0

        async def search(self, **kwargs):
            self.active += 1
            self.peak = max(self.peak, self.active)
            await asyncio.sleep(0.01)
            self.active -= 1
            return await super().search(**kwargs)

    packets = []
    for index in range(1, 6):
        original = packet()
        payload = copy.deepcopy(original.packet)
        instrument_id = UUID(int=index)
        payload["identity"]["instrument_id"] = str(instrument_id)
        packets.append(replace(
            original, instrument_id=instrument_id,
            packet=payload, packet_hash=_canonical_hash(payload),
        ))
    client = Concurrent()
    enricher = LlmSearchEnricher(
        config(), artifact_directory=tmp_path, client=client, max_concurrency=3,
    )

    async def execute():
        first = await enricher.enrich(tuple(packets), knowledge_mode="HISTORICAL_RECONSTRUCTION")
        second = await enricher.enrich(tuple(packets), knowledge_mode="HISTORICAL_RECONSTRUCTION")
        return first, second

    first, second = asyncio.run(execute())
    assert client.peak == 3
    assert len(client.requests) == 5
    assert first == second
    assert [value.instrument_id for value in first] == [value.instrument_id for value in packets]


def test_retry_after_partial_failure_does_not_search_completed_packet_again(tmp_path):
    class Partial(SearchClient):
        failing = True
        failed_calls = 0

        async def search(self, **kwargs):
            if kwargs["public_input"]["ticker"] == "FAIL":
                self.failed_calls += 1
                if self.failing:
                    httpx.Response(
                        500, request=httpx.Request("POST", self.endpoint),
                    ).raise_for_status()
            return await super().search(**kwargs)

    first = packet()
    payload = copy.deepcopy(first.packet)
    payload["identity"]["instrument_id"] = str(UUID(int=99))
    failed = replace(
        first, instrument_id=UUID(int=99), symbol="FAIL",
        packet=payload, packet_hash=_canonical_hash(payload),
    )
    client = Partial()
    policy = replace(config(), base_delay_seconds=0)
    enricher = LlmSearchEnricher(policy, artifact_directory=tmp_path, client=client)

    async def execute():
        with pytest.raises(SearchProviderError):
            await enricher.enrich((first, failed), knowledge_mode="HISTORICAL_RECONSTRUCTION")
        client.failing = False
        return await enricher.enrich(
            (first, failed), knowledge_mode="HISTORICAL_RECONSTRUCTION",
        )

    assert len(asyncio.run(execute())) == 2
    assert len(client.requests) == 2
    assert client.failed_calls == policy.max_attempts + 1


@pytest.mark.parametrize("max_delay,expected_delays", [(60, [2.0]), (1, [])])
def test_search_respects_retry_after_and_delay_budget(
    monkeypatch, tmp_path, max_delay, expected_delays,
):
    class Throttled(SearchClient):
        calls = 0

        async def search(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                httpx.Response(
                    429, headers={"Retry-After": "2"},
                    request=httpx.Request("POST", self.endpoint),
                ).raise_for_status()
            return await super().search(**kwargs)

    delays = []

    async def sleep(delay):
        delays.append(delay)

    monkeypatch.setattr(asyncio, "sleep", sleep)
    enricher = LlmSearchEnricher(
        replace(config(), base_delay_seconds=0, max_delay_seconds=max_delay),
        artifact_directory=tmp_path, client=Throttled(),
    )

    async def execute():
        return await enricher._search(instructions="public", public_input={}, context_key="context")

    if expected_delays:
        assert asyncio.run(execute()) == response()
    else:
        with pytest.raises(SearchProviderError):
            asyncio.run(execute())
    assert delays == expected_delays


class SearchClient:
    endpoint = "https://model.example.test"
    deployment = "search-model"
    binding_key = "test-native-search"

    def __init__(self, raw=None):
        self.raw = raw or response()
        self.requests = []
        self.scoring_requests = []
        self.pinned_model = None

    async def search(self, **kwargs):
        self.requests.append(kwargs)
        return copy.deepcopy(self.raw)

    async def complete(self, *, messages, **kwargs):
        self.scoring_requests.append(messages)
        self.pinned_model = kwargs.get("expected_model_version")
        row = json.loads(messages[1]["content"])[0]
        evidence = row["packet"]["filings"][0].get("search_evidence")
        return AzureOpenAIResponse(
            {
                "assessments": [
                    {
                        "instrument_id": row["instrument_id"],
                        "scores": {
                            "earnings": 80,
                            "business": 80,
                            "event": 80,
                            "financial": None,
                            "industry": None,
                        },
                        "missing_reasons": {
                            "earnings": None,
                            "business": None,
                            "event": None,
                            "financial": "재무 수치가 없습니다.",
                            "industry": "산업 비교가 없습니다.",
                        },
                        "evidence_quality": "MEDIUM",
                        "uncertainty": "MEDIUM",
                        "summary": "제공 사실을 평가했습니다.",
                        "information_gaps": [SEARCH_OMISSION_GAP] if evidence is None
                        else ["계약 상세는 확인되지 않았습니다."],
                        "evidence": [
                            {
                                "evidence_link_id": str(UUID(int=3)),
                                "criterion": key,
                                "reason": "제공된 사업 현황을 평가했습니다.",
                                "source_layer": "DB_PACKET",
                                "search_evidence_hash": None,
                            }
                            for key in ("earnings", "business")
                        ]
                        + [
                            {
                                "evidence_link_id": str(UUID(int=5 if evidence else 3)),
                                "criterion": "event",
                                "reason": "게이트를 통과한 검색 발췌를 평가했습니다.",
                                "source_layer": "LLM_SEARCH_VERIFIED" if evidence else "DB_PACKET",
                                "search_evidence_hash": evidence["evidence_hash"]
                                if evidence else None,
                            }
                        ],
                    }
                ]
            },
            10,
            10,
            20,
        )


def enrich(tmp_path, client=None, value=None, mode="HISTORICAL_RECONSTRUCTION"):
    client = client or SearchClient()
    enricher = LlmSearchEnricher(config(), artifact_directory=tmp_path, client=client)
    enriched = asyncio.run(enricher.enrich((value or packet(),), knowledge_mode=mode))[0]
    return enriched, enricher, client


def optional_config():
    original = config()
    return replace(
        original, enrichment=replace(original.enrichment, on_admission_failure="OMIT_EXTERNAL")
    )


def test_optional_search_still_searches_then_scores_only_database_after_rejection(tmp_path):
    raw = response()
    raw["output"][1]["content"][0]["text"] += "\n2027년 실제 이익을 알고 있습니다."
    client = SearchClient(raw)
    options = optional_config()
    enricher = LlmSearchEnricher(options, artifact_directory=tmp_path, client=client)

    async def run():
        [value] = await enricher.enrich((packet(),), knowledge_mode="HISTORICAL_RECONSTRUCTION")
        validate_model_packets((value,), require_enrichment=True, allow_omitted_enrichment=True)
        with pytest.raises(ValueError, match="admitted tool evidence"):
            validate_model_packets((value,), require_enrichment=True)
        with pytest.raises(ValueError, match="explicitly"):
            validate_model_packets((value,))
        ranker = EventPreselectionRanker(
            LlmRankerSettings("https://model.example.test", "model", "test"),
            options, client=client,
        )
        result = await ranker.rank(llm_ranking_run_id=UUID(int=3000), packets=(value,))
        return value, result

    value, result = asyncio.run(run())
    assert len(client.requests) == len(client.scoring_requests) == 1
    assert result.assessments[0].score == 80
    assert "EXTERNAL_NEWS_NOT_USED" in result.assessments[0].reason_codes
    assert value.packet["news"] == packet().packet["news"]
    assert "llm_search_manifest_hash" not in value.packet
    assert "search_evidence" not in value.packet["filings"][0]
    assert "2027년" not in json.dumps(client.scoring_requests, ensure_ascii=False)
    marker = value.packet["llm_search_omission"]
    assert marker["information_gap"] == SEARCH_OMISSION_GAP
    audit = json.loads((tmp_path / marker["artifact_key"]).read_text())
    assert audit["reason_code"] == marker["reason_code"]
    assert (tmp_path / audit["source_artifact_key"]).exists()


def test_optional_policy_preserves_successful_enrichment(tmp_path):
    client = SearchClient()
    enricher = LlmSearchEnricher(optional_config(), artifact_directory=tmp_path, client=client)
    [value] = asyncio.run(enricher.enrich((packet(),), knowledge_mode="HISTORICAL_RECONSTRUCTION"))
    assert value.packet["filings"][0]["search_evidence"]
    assert "llm_search_omission" not in value.packet


def test_optional_omission_replays_exact_audit_and_rejects_missing_artifacts(tmp_path):
    raw = response()
    raw["output"][0]["action"]["sources"] = []
    client = SearchClient(raw)
    enricher = LlmSearchEnricher(optional_config(), artifact_directory=tmp_path, client=client)

    def run(value):
        return asyncio.run(enricher.enrich((value,), knowledge_mode="HISTORICAL_RECONSTRUCTION"))[0]

    omitted = run(packet())
    assert run(omitted) == omitted
    assert len(client.requests) == 1
    path = tmp_path / omitted.packet["llm_search_omission"]["artifact_key"]
    audit = json.loads(path.read_text())
    source = tmp_path / audit["source_artifact_key"]
    original = source.read_text(encoding="utf-8")
    source.write_text("{}", encoding="utf-8")
    with pytest.raises(ExternalEvidenceError, match="missing or changed"):
        run(omitted)
    source.write_text(original, encoding="utf-8")
    path.unlink()
    with pytest.raises(ExternalEvidenceError, match="audit artifact is missing"):
        run(omitted)


def test_optional_search_does_not_hide_provider_authentication_errors(tmp_path):
    class Unauthorized(SearchClient):
        async def search(self, **kwargs):
            response = httpx.Response(401, request=httpx.Request("POST", self.endpoint))
            response.raise_for_status()

    enricher = LlmSearchEnricher(
        optional_config(), artifact_directory=tmp_path, client=Unauthorized(),
    )
    with pytest.raises(SearchProviderError, match="401"):
        asyncio.run(enricher.enrich((packet(),), knowledge_mode="HISTORICAL_RECONSTRUCTION"))
    artifacts = [json.loads(path.read_text()) for path in tmp_path.glob("*.json")]
    assert len(artifacts) == 1
    assert artifacts[0]["schema_version"] == "llm-search-provider-failure-v1"
    assert artifacts[0]["http_status"] == 401
    assert artifacts[0]["retryable"] is False


def test_optional_search_does_not_hide_database_cutoff_errors(tmp_path):
    raw = response()
    raw["output"][0]["action"]["sources"] = []
    value = packet()
    changed = replace(
        value, links=(replace(value.links[0], source_available_at=datetime(2027, 1, 1, tzinfo=UTC)),
                      *value.links[1:]),
    )
    enricher = LlmSearchEnricher(
        optional_config(), artifact_directory=tmp_path, client=SearchClient(raw),
    )
    with pytest.raises(ValueError):
        asyncio.run(enricher.enrich((changed,), knowledge_mode="HISTORICAL_RECONSTRUCTION"))


def test_optional_search_cannot_be_used_under_a_mandatory_policy(tmp_path):
    raw = response()
    raw["output"][0]["action"]["sources"] = []
    client = SearchClient(raw)
    optional = LlmSearchEnricher(optional_config(), artifact_directory=tmp_path, client=client)
    [value] = asyncio.run(optional.enrich((packet(),), knowledge_mode="HISTORICAL_RECONSTRUCTION"))
    required = LlmSearchEnricher(config(), artifact_directory=tmp_path, client=client)
    with pytest.raises(ExternalEvidenceError, match="explicit policy"):
        asyncio.run(required.enrich((value,), knowledge_mode="HISTORICAL_RECONSTRUCTION"))


def test_native_request_has_provider_tool_and_no_external_gets():
    seen = []

    def handler(request):
        seen.append(request)
        assert request.method == "POST" and request.url.host == "resource.openai.azure.com"
        body = json.loads(request.content)
        assert body["tools"][0]["type"] == "web_search"
        assert body["include"] == ["web_search_call.action.sources"]
        assert body["store"] is False and "previous_response_id" not in body
        assert body["max_tool_calls"] == 2
        return httpx.Response(200, json=response())

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
            client = AzureOpenAIClient(
                endpoint="https://resource.openai.azure.com",
                deployment="model",
                api_version="test",
                timeout_seconds=30,
                client=transport,
                credential=SimpleNamespace(
                    get_token=lambda *args: SimpleNamespace(token="test-only")
                ),
            )
            return await client.search(
                instructions="검색하세요",
                public_input={
                    "company_name": "Example Issuer",
                    "ticker": "TEST",
                    "cik": "123",
                    "cutoff_at": CUTOFF.isoformat(),
                    "archive_sources": [
                        {
                            "accession": ACCESSION,
                            "form": "8-K",
                            "published_at": ACCEPTED.isoformat(),
                            "archive_path": "/Archives/edgar/data/123/000000012326000001/",
                        }
                    ],
                },
                max_tool_calls=2,
                max_response_bytes=100000,
            )

    assert asyncio.run(run())["status"] == "completed"
    assert len(seen) == 1 and seen[0].url.path == "/openai/v1/responses"


def test_search_uses_only_public_metadata_and_produces_bound_evidence(tmp_path):
    enriched, _, client = enrich(tmp_path)
    public = json.dumps(client.requests[0]["public_input"])
    assert "private-db-only" not in public
    assert str(UUID(int=1000)) not in public and str(UUID(int=1)) not in public
    assert "issuer_id" not in public and "packet" not in public
    assert client.requests[0]["public_input"]["ticker"] == "TEST"
    assert enriched.packet["filings"][0]["search_evidence"][
        "tool_response_hash"
    ] == _canonical_hash(response())
    validate_model_packets((enriched,), require_enrichment=True)
    with pytest.raises(ValueError, match="explicitly"):
        validate_model_packets((enriched,))


@pytest.mark.parametrize(
    "bad",
    [
        "future_url",
        "uncited_current_url",
        "future_text",
        "uncited_future_text",
        "future_query",
        "future_metadata",
        "no_tools",
        "no_sources",
        "incomplete",
        "previous_context",
        "uncited_url",
        "wrong_date",
        "bad_offsets",
        "no_body",
        "wrong_company",
        "future_to_original",
        "future_quarter",
        "over_budget",
        "unexpected_tool",
    ],
)
def test_any_unsafe_search_is_rejected_whole_and_never_scored(tmp_path, bad):
    raw = response()
    action = raw["output"][0]["action"]
    content = raw["output"][1]["content"][0]
    if bad in {"future_url", "uncited_current_url"}:
        action["sources"].append(
            {
                "type": "url",
                "url": (
                    "https://www.sec.gov/Archives/edgar/data/123/0000000123-27-000001.txt"
                    if bad == "future_url"
                    else "https://news.example.test/current"
                ),
            }
        )
    elif bad in {"future_text", "uncited_future_text"}:
        content["text"] += "\n2027년 실제 이익을 알고 있습니다."
    elif bad == "future_query":
        action["queries"] = ["company 2027 actual earnings"]
    elif bad == "future_metadata":
        action["sources"][0]["published_at"] = "2027-01-01T00:00:00+00:00"
    elif bad == "no_tools":
        raw["output"].pop(0)
    elif bad == "no_sources":
        action.pop("sources")
    elif bad == "incomplete":
        raw["status"] = "incomplete"
    elif bad == "previous_context":
        raw["previous_response_id"] = "resp_other"
    elif bad == "uncited_url":
        content["annotations"][0]["url"] = "https://www.sec.gov/current"
    elif bad == "wrong_date":
        content["text"] = content["text"].replace("2026-10-14", "2026-10-13")
    elif bad == "bad_offsets":
        content["annotations"][0]["end_index"] = 999999
    elif bad == "no_body":
        content["text"] = content["text"].replace(
            "과거 공시에서 제공된 사업 현황을 확인했습니다.", "본문 확인 불가"
        )
        content["annotations"][0]["start_index"] = content["text"].index("[1]")
        content["annotations"][0]["end_index"] = len(content["text"])
    elif bad in {"future_to_original", "future_quarter"}:
        addition = (
            " 2026-10-15에 발생한 일을 알았습니다."
            if bad == "future_to_original"
            else " 2026년 4분기 실제 실적입니다."
        )
        content["text"] = content["text"].replace(" [1]", addition + " [1]")
        content["annotations"][0]["start_index"] = content["text"].index("[1]")
        content["annotations"][0]["end_index"] = len(content["text"])
    elif bad == "over_budget":
        raw["output"].extend([copy.deepcopy(raw["output"][0])] * 2)
    elif bad == "unexpected_tool":
        raw["output"].append({"type": "file_search_call", "status": "completed"})
    else:
        action["sources"][0]["url"] = URL.replace("/123/", "/456/")
    client = SearchClient(raw)
    with pytest.raises(ExternalEvidenceError):
        enrich(tmp_path, client)
    assert not client.scoring_requests
    decision = json.loads(next(tmp_path.glob("*.admission.json")).read_text(encoding="utf-8"))
    assert decision["status"] == "REJECTED" and decision["scoring_allowed"] is False


def test_late_operational_search_fails_without_a_tool_call(tmp_path):
    client = SearchClient()
    with pytest.raises(ExternalEvidenceError, match="operational replay"):
        enrich(tmp_path, client, mode="OPERATIONAL_REPLAY")
    assert not client.requests


def test_search_cache_binds_context_and_replays_without_network(tmp_path):
    enriched, enricher, client = enrich(tmp_path)
    replay = asyncio.run(enricher.enrich((enriched,), knowledge_mode="HISTORICAL_RECONSTRUCTION"))[
        0
    ]
    assert replay.packet_hash == enriched.packet_hash and len(client.requests) == 1
    tampered = copy.deepcopy(enriched.packet)
    tampered["identity"]["company_name"] = "different base"
    changed = replace(enriched, packet=tampered, packet_hash=_canonical_hash(tampered))
    with pytest.raises(ExternalEvidenceError, match="identity/hash"):
        asyncio.run(enricher.enrich((changed,), knowledge_mode="HISTORICAL_RECONSTRUCTION"))
    artifact = tmp_path / enriched.packet["filings"][0]["search_evidence"]["artifact_key"]
    artifact.write_text("{}", encoding="utf-8")
    with pytest.raises(ExternalEvidenceError, match="identity/hash"):
        asyncio.run(enricher.enrich((enriched,), knowledge_mode="HISTORICAL_RECONSTRUCTION"))


def test_only_cited_passages_cross_into_a_new_scoring_conversation(tmp_path):
    raw = response()
    raw["output"][1]["content"][0]["text"] += "\nUNCITED_SEARCH_ONLY_MARKER"
    client = SearchClient(raw)
    enriched, _, _ = enrich(tmp_path, client)
    ranker = EventPreselectionRanker(
        LlmRankerSettings(client.endpoint, client.deployment, "test"),
        config(),
        client=client,
    )
    result = asyncio.run(ranker.rank(llm_ranking_run_id=UUID(int=1001), packets=(enriched,)))
    assert result.assessments[0].score == 80
    assert client.pinned_model is None
    scoring = json.dumps(client.scoring_requests[0])
    assert "UNCITED_SEARCH_ONLY_MARKER" not in scoring
    assert "web_search_call" not in scoring and "resp_test" not in scoring
    assert [item["role"] for item in client.scoring_requests[0]] == ["system", "user"]
    assert result.assessments[0].criterion_evidence[-1]["source_layer"] == "LLM_SEARCH_VERIFIED"


@pytest.mark.parametrize(
    "url",
    [
        "https://sec.gov.evil.test/current",
        "http://www.sec.gov/current",
        "https://www.sec.gov/Archives/edgar/data/123/index.json",
        "https://www.sec.gov/ixviewer/doc?action=current",
    ],
)
def test_current_or_mutable_urls_are_not_publication_proof(url):
    with pytest.raises(ValueError):
        source_filing(url, "123", [FILING], CUTOFF)


def test_required_search_evidence_cannot_be_bypassed_by_a_base_packet():
    client = SearchClient()
    ranker = EventPreselectionRanker(
        LlmRankerSettings(client.endpoint, client.deployment, "test"),
        config(),
        client=client,
    )
    with pytest.raises(ValueError, match="schema 4"):
        asyncio.run(ranker.rank(llm_ranking_run_id=UUID(int=1001), packets=(packet(),)))
    assert not client.scoring_requests


def test_private_packet_is_rejected_at_the_native_api_boundary():
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: pytest.fail("Private input must not issue an HTTP request")
            )
        ) as transport:
            client = AzureOpenAIClient(
                endpoint="https://resource.openai.azure.com",
                deployment="model",
                api_version="test",
                timeout_seconds=30,
                client=transport,
                credential=SimpleNamespace(
                    get_token=lambda *args: SimpleNamespace(token="test-only")
                ),
            )
            await client.search(
                instructions="검색",
                public_input={"packet": packet().packet},
                max_tool_calls=2,
                max_response_bytes=100000,
            )

    with pytest.raises(ValueError, match="public metadata whitelist"):
        asyncio.run(run())


def test_response_model_alias_does_not_block_a_scoring_response():
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={
                        "model": "model-latest",
                        "choices": [{"message": {"content": '{"ok":true}'}}],
                        "usage": {},
                    },
                )
            )
        ) as transport:
            client = AzureOpenAIClient(
                endpoint="https://resource.openai.azure.com",
                deployment="model",
                api_version="test",
                timeout_seconds=30,
                client=transport,
                credential=SimpleNamespace(
                    get_token=lambda *args: SimpleNamespace(token="test-only")
                ),
            )
            result = await client.complete(
                messages=[],
                schema_name="test",
                schema={},
            )
            assert result.output == {"ok": True}

    asyncio.run(run())


@pytest.mark.parametrize(
    "model",
    [
        "gpt-6.1-sol",
        "model-latest",
        "model-2027-01-01",
        None,
    ],
)
def test_publication_and_original_version_not_model_metadata_decide_admission(tmp_path, model):
    raw = response()
    if model is None:
        raw.pop("model")
    else:
        raw["model"] = model
    enriched, _, _ = enrich(tmp_path, SearchClient(raw))
    evidence = enriched.packet["filings"][0]["search_evidence"]
    assert evidence["model_snapshot"] == model
    validate_model_packets((enriched,), require_enrichment=True)


@pytest.mark.parametrize(
    "mode", ["native", "native_mixed", "omitted", "period_day", "period_timestamp"],
)
def test_search_witness_survives_typed_fusion_projection(tmp_path, mode):
    from dataclasses import asdict

    from pydantic import TypeAdapter

    from sp500_candidate_engine.database import _stable_uuid
    from sp500_candidate_engine.fusion.explanations import (
        CandidateExplanation,
        Contribution,
        ExternalEvidenceExplanation,
        FusionExplanation,
        LlmExplanation,
        QuantExplanation,
        _project_evidence,
        explanation_payload,
    )

    if mode == "omitted":
        raw = response()
        raw["output"][0]["action"]["sources"] = []
        enricher = LlmSearchEnricher(
            optional_config(), artifact_directory=tmp_path, client=SearchClient(raw),
        )
        [enriched] = asyncio.run(
            enricher.enrich((packet(),), knowledge_mode="HISTORICAL_RECONSTRUCTION")
        )
    elif mode.startswith("period"):
        from sp500_candidate_engine.llm_preselection.enrichment_contract import (
            validate_search_response,
        )

        raw = response()
        raw["output"][0] = {
            "type": "bing_grounding_call", "status": "completed", "call_id": "period",
        }
        raw["output"].insert(1, {
            "type": "bing_grounding_call_output", "status": "completed", "call_id": "period",
        })
        label = "2026-10-13" if mode == "period_day" else "2026-10-15 04:00"
        content = raw["output"][-1]["content"][0]
        content["text"] = f"{label} | 검증된 사업 현황을 확인했습니다. [1]"
        content["annotations"] = [{
            "type": "url_citation", "url": "https://news.example.test/story",
            "start_index": content["text"].index("[1]"), "end_index": len(content["text"]),
        }]
        [(filing_id, document)] = validate_search_response(
            raw, cik="123", filings=[FILING], cutoff_at=CUTOFF, observed_at=CUTOFF,
            knowledge_mode="HISTORICAL_RECONSTRUCTION", artifact_key="0" * 64 + ".json",
            max_tool_calls=2, max_facts=8, provider="AZURE_BING_GROUNDING_PERIOD",
            source_pages={"https://news.example.test/story": {
                "status": "ADMITTED", "label": label,
                "precision": "DAY" if mode == "period_day" else "TIMESTAMP",
            }},
        )
        enriched = packet()
        payload = copy.deepcopy(enriched.packet)
        payload["filings"][0]["search_evidence"] = document.payload()
        payload["llm_search_manifest_hash"] = _canonical_hash([{
            "filing_id": filing_id, "evidence": document.payload(),
        }])
        enriched = replace(enriched, packet=payload, packet_hash=_canonical_hash(payload))
    else:
        enriched, _, _ = enrich(tmp_path)
    run_id = UUID(int=1001)
    links = [
        replace(
            link,
            evidence_link_id=_stable_uuid(
                "llm-run-evidence-link",
                (
                    f"{run_id}:{enriched.instrument_id}:{link.source_kind}:{link.entity_key}:{link.source_snapshot_id}"
                ),
            ),
        )
        for link in enriched.links
    ]
    identifier = str(links[-1].evidence_link_id)
    search = enriched.packet["filings"][0].get("search_evidence")
    row = {
        "packet": enriched.packet,
        "packet_hash": enriched.packet_hash,
        "instrument_id": enriched.instrument_id,
        "issuer_id": enriched.issuer_id,
        "sub_scores": {
            "earnings": 80,
            "business": 80,
            "event": 80,
            "financial": None,
            "industry": None,
        },
        "missing_reasons": {"financial": "재무 부족", "industry": "산업 비교 부족"},
        "criterion_evidence": [
            {
                "evidence_link_id": identifier,
                "criterion": key,
                "reason": "승인된 검색 발췌를 평가했습니다.",
                "source_layer": "LLM_SEARCH_VERIFIED" if search else "DB_PACKET",
                "search_evidence_hash": search["evidence_hash"] if search else None,
            }
            for key in ("earnings", "business", "event")
        ],
        "evidence_ids": [identifier],
        "evidence_links": [
            {
                **asdict(link),
                "instrument_id": enriched.instrument_id,
                "manifest_member": True,
                "revision_no": 1,
                "revision_observed_at": ACCEPTED,
            }
            for link in links
        ],
    }
    if search:
        row["criterion_evidence"].append({
            **row["criterion_evidence"][0],
            "reason": "같은 검증 자료의 별도 사업 사실을 반영했습니다.",
        })
    if mode == "native_mixed":
        row["criterion_evidence"].append({
            **row["criterion_evidence"][0], "source_layer": "DB_PACKET",
            "search_evidence_hash": None, "reason": "별도로 제공된 DB 근거를 반영했습니다.",
        })
    context = {
        "execution_context_id": UUID(int=1000),
        "cutoff_at": CUTOFF,
        "knowledge_mode": "HISTORICAL_RECONSTRUCTION",
    }
    scores, missing, evidence = _project_evidence(
        row,
        context=context,
        target_session=DAY,
        rationale_limit=600,
        llm_ranking_run_id=run_id,
    )
    assert len(evidence) == (4 if mode == "native_mixed" else 3)
    if search:
        assert "승인된 검색 발췌" in evidence[0].summary
        assert "별도 사업 사실" in evidence[0].summary
        invalid = copy.deepcopy(row)
        invalid["criterion_evidence"].append(copy.deepcopy(row["criterion_evidence"][0]))
        with pytest.raises(ValueError, match="Duplicate external explanation reason"):
            _project_evidence(
                invalid, context=context, target_session=DAY, rationale_limit=600,
                llm_ranking_run_id=run_id,
            )
    snapshot = CandidateExplanation(
        "candidate-explanation-v3",
        "RECORDED",
        DAY,
        CUTOFF,
        UUID(int=1000),
        "검색 평가",
        QuantExplanation(
            False, UUID(int=10), "PREDICTED_20D_RETURN", None, None, None, (), "정량 원천 미포함"
        ),
        LlmExplanation(
            True,
            UUID(int=20),
            80,
            1,
            3,
            70,
            "DETERMINISTIC_CITATIONS",
            "검색 평가",
            scores,
            missing,
            evidence,
        ),
        FusionExplanation(10, None, Contribution(1, 11), 1, 11, 1, ("RRF_LLM_ONLY",), False),
    )
    restored = TypeAdapter(CandidateExplanation).validate_python(explanation_payload(snapshot))
    if mode == "omitted":
        assert not isinstance(restored.llm.evidence[0], ExternalEvidenceExplanation)
    else:
        assert isinstance(restored.llm.evidence[0], ExternalEvidenceExplanation)
        assert restored.llm.evidence[0].external_source.model_snapshot == "search-model-2026-09-29"
        assert restored.llm.evidence[0].external_source.evidence_hash == search["evidence_hash"]
        external = restored.llm.evidence[0].external_source
        if mode == "native_mixed":
            assert not isinstance(restored.llm.evidence[-1], ExternalEvidenceExplanation)
        if mode.startswith("period"):
            assert external.verification_method == "PERIOD_SEARCH_SOURCE_DATES"
            assert external.source_available_at == CUTOFF
            assert external.source_local_date != date.fromisoformat(FILING["filed_date"])
            with pytest.raises(ValueError, match="external explanation witness"):
                replace(snapshot, llm=replace(snapshot.llm, evidence=(
                    replace(evidence[0], external_source=replace(
                        evidence[0].external_source, source_date_precision=(
                            "TIMESTAMP" if mode == "period_day" else "DAY"
                        ),
                    )),
                    *evidence[1:],
                )))
        else:
            assert external.verification_method == "NATIVE_SEARCH_PINNED_ARCHIVE"
