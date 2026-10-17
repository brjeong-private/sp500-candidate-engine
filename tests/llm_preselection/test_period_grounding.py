import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from sp500_candidate_engine.analytics.azure_openai import (
    AzureOpenAIClient,
    BingGroundingConnection,
    BingGroundingSearchClient,
)
from sp500_candidate_engine.llm_preselection.config import load_llm_preselection_config
from sp500_candidate_engine.llm_preselection.enrichment_contract import validate_search_response
from sp500_candidate_engine.llm_preselection.source_dates import (
    SourceDateError,
    public_host_allowed,
    source_bound,
)

CUTOFF = datetime(2026, 10, 17, 9, 30, tzinfo=UTC)
CONNECTION = (
    "/subscriptions/sub/resourceGroups/group/providers/Microsoft.CognitiveServices/"
    "accounts/resource/projects/project/connections/bing"
)
ENDPOINT = "https://resource.services.ai.azure.com/api/projects/project"


def test_date_range_is_a_bing_tool_parameter_not_just_prompt():
    requests = []

    def handler(request):
        requests.append(request)
        assert request.method == "POST"
        assert request.url.host == "resource.services.ai.azure.com"
        body = json.loads(request.content)
        tool = body["tools"][0]
        assert tool["type"] == "bing_grounding"
        search = tool["bing_grounding"]["search_configurations"][0]
        assert search["freshness"] == "2026-10-10..2026-10-17"
        assert search["project_connection_id"] == CONNECTION
        assert body["tool_choice"] == "required"
        assert body["store"] is False
        return httpx.Response(200, json={"status": "completed", "output": []})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as transport:
            api = AzureOpenAIClient(
                endpoint="https://resource.openai.azure.com",
                deployment="model",
                api_version="test",
                timeout_seconds=30,
                client=transport,
                credential=SimpleNamespace(
                    get_token=lambda *scopes: SimpleNamespace(token="test-only")
                ),
            )
            client = BingGroundingSearchClient(
                api,
                BingGroundingConnection(ENDPOINT, CONNECTION, lookback_days=7),
            )
            await client.search(
                instructions="조사",
                public_input={
                    "company_name": "Public Company",
                    "ticker": "TEST",
                    "cik": "123",
                    "cutoff_at": CUTOFF.isoformat(),
                    "archive_sources": [
                        {
                            "accession": "0000000123-26-000001",
                            "form": "8-K",
                            "published_at": "2026-10-16",
                            "archive_path": "/Archives/edgar/data/123/000000012326000001/",
                        }
                    ],
                },
                max_tool_calls=2,
                max_response_bytes=100000,
            )

    asyncio.run(run())
    assert len(requests) == 1


def test_period_policy_is_explicit_and_keeps_original_version_guard():
    config = load_llm_preselection_config(
        Path(__file__).parents[2] / "config" / "llm_preselection" / "policy_event_period_v5.yaml"
    )
    assert config.enrichment.provider == "AZURE_BING_GROUNDING_PERIOD"
    assert config.windows.news_days == 30
    assert config.evidence_schema_version == "4"


def _bing_raw(url: str, text: str) -> dict:
    return {
        "status": "completed",
        "output": [
            {"type": "bing_grounding_call", "status": "completed", "call_id": "call1"},
            {
                "type": "bing_grounding_call_output",
                "status": "completed",
                "call_id": "call1",
                "output": "",
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
                                "url": url,
                                "start_index": len(text) - 1,
                                "end_index": len(text),
                            }
                        ],
                    }
                ],
            },
        ],
    }


FILING = {
    "filing_id": "f1",
    "accession_no": "0000000123-26-000001",
    "accepted_at": "2026-10-16T12:00:00+00:00",
}


def _admit(url: str, text: str, ledger: dict):
    return validate_search_response(
        _bing_raw(url, text),
        cik="123",
        filings=[FILING],
        cutoff_at=CUTOFF,
        observed_at=CUTOFF,
        knowledge_mode="HISTORICAL_RECONSTRUCTION",
        artifact_key="0" * 64 + ".json",
        max_tool_calls=2,
        max_facts=8,
        provider="AZURE_BING_GROUNDING_PERIOD",
        source_pages=ledger,
    )


def test_period_news_with_python_read_previous_day_is_admitted():
    url = "https://news.example.test/2026/10/15/story"
    ledger = {
        url: {"status": "ADMITTED", "label": "2026-10-15", "precision": "DAY"},
    }
    [(key, evidence)] = _admit(url, "2026-10-15 | 정제 마진이 개선됐다고 보도했다.[1]", ledger)
    assert key == "f1"
    assert evidence.facts[0].value.startswith("2026-10-15 | 정제 마진")
    assert evidence.source_date_precision == "DAY"


def test_period_news_without_admitted_python_date_is_rejected():
    url = "https://news.example.test/story"
    ledger = {url: {"status": "REJECTED", "reason": "SOURCE_DATE_NOT_FOUND"}}
    with pytest.raises(ValueError, match="NO_BOUNDED_ADMISSIBLE_FACTS"):
        _admit(url, "2026-10-15 | 날짜 없는 기사.[1]", ledger)


def test_page_dates_follow_new_york_day_and_0530_rule():
    cutoff = CUTOFF
    old = source_bound("https://x.test/2026/10/15/a", "", cutoff)[0]
    assert old.precision == "DAY"
    page = '<meta property="article:published_time" content="2026-10-17T04:00:00-04:00">'
    assert source_bound("https://x.test/a", page, cutoff)[0].precision == "TIMESTAMP"
    late = '<meta property="article:published_time" content="2026-10-17T05:31:00-04:00">'
    with pytest.raises(SourceDateError):
        source_bound("https://x.test/a", late, cutoff)
    with pytest.raises(SourceDateError):
        source_bound("https://x.test/2026/10/17/a", "", cutoff)
    with pytest.raises(SourceDateError):
        source_bound("https://x.test/2026/10/18/a", "", cutoff)
    with pytest.raises(SourceDateError):
        source_bound("https://x.test/a", "<html></html>", cutoff)
    # A page stamp later than the URL date wins, so a stale URL cannot hide a same-day page.
    with pytest.raises(SourceDateError):
        source_bound("https://x.test/2026/10/15/a", late, cutoff)


def test_private_hosts_are_not_fetched():
    assert not public_host_allowed("x.test", ["127.0.0.1"])
    assert not public_host_allowed("x.test", ["10.0.0.5", "93.184.216.34"])
    assert public_host_allowed("x.test", ["93.184.216.34"])

