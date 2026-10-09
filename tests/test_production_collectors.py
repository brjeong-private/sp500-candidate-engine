import asyncio
from datetime import date, datetime
from unittest.mock import patch

import httpx
import pytest

from sp500_candidate_engine.collectors.alpha_vantage import (
    AlphaVantageEarningsCollector,
)
from sp500_candidate_engine.collectors.massive import MassiveCollector
from sp500_candidate_engine.collectors.sec import SecCollector
from sp500_candidate_engine.http import ProviderRequestError, RetryingHttpClient
from sp500_candidate_engine.models import UTC, KnowledgeMode, RunSpec
from sp500_candidate_engine.temporal import FutureDataViolation


class FakeResponseClient:
    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        self.params: dict[str, str | int] | None = None

    async def get(
        self,
        _url: str,
        *,
        params: dict[str, str | int] | None = None,
    ) -> httpx.Response:
        del _url
        self.params = params
        return self.response


def test_massive_grouped_parser_rejects_future_session() -> None:
    spec = RunSpec.for_date(date(2026, 10, 1), KnowledgeMode.HISTORICAL_RECONSTRUCTION)
    payload = {
        "results": [
            {
                "T": "AAPL",
                "t": int(datetime(2026, 10, 2, 4, 0, tzinfo=UTC).timestamp() * 1000),
                "o": 1,
                "h": 2,
                "l": 1,
                "c": 2,
                "v": 100,
            }
        ]
    }
    with pytest.raises(FutureDataViolation):
        MassiveCollector._parse_grouped(payload, spec, {"AAPL": "AAPL"})


def test_massive_dividend_parser_excludes_future_declaration() -> None:
    spec = RunSpec.for_date(date(2026, 10, 1), KnowledgeMode.HISTORICAL_RECONSTRUCTION)
    actions = MassiveCollector._parse_actions(
        [
            {
                "id": "future",
                "ticker": "AAPL",
                "ex_dividend_date": "2026-10-10",
                "declaration_date": "2026-10-02",
                "cash_amount": 0.25,
            }
        ],
        [],
        spec,
        {"AAPL": "AAPL"},
    )
    assert actions == ()


def test_alpha_earnings_uses_one_all_symbols_request() -> None:
    csv_body = (
        "symbol,name,reportDate,fiscalDateEnding,estimate,currency,timeOfTheDay\n"
        "AAPL,Apple Inc,2026-10-29,2026-09-30,1.5,USD,amc\n"
    )
    response = httpx.Response(
        200,
        text=csv_body,
        headers={"content-type": "text/csv"},
        request=httpx.Request("GET", "https://example.invalid"),
    )
    collector = AlphaVantageEarningsCollector(
        base_url="https://example.invalid",
        api_key="secret",
        timeout_seconds=1,
        max_attempts=1,
        user_agent="test",
    )
    fake = FakeResponseClient(response)
    with patch.object(collector, "client", fake):
        collection = asyncio.run(collector.collect())
    assert len(collection.events) == 1
    assert fake.params is not None
    assert "symbol" not in fake.params
    assert fake.params["function"] == "EARNINGS_CALENDAR"


def test_sec_reference_parser_maps_fields() -> None:
    response = httpx.Response(
        200,
        json={
            "fields": ["cik", "name", "ticker", "exchange"],
            "data": [[320193, "Apple Inc.", "AAPL", "Nasdaq"]],
        },
        request=httpx.Request("GET", "https://example.invalid"),
    )
    collector = SecCollector(
        timeout_seconds=1,
        max_attempts=1,
        user_agent="candidate-engine contact@example.com",
    )
    with patch.object(collector, "client", FakeResponseClient(response)):
        collection = asyncio.run(collector.collect_reference())
    assert collection.companies[0].cik == "0000320193"
    assert collection.companies[0].exchange == "Nasdaq"


def test_http_errors_do_not_expose_query_secret() -> None:
    async def run() -> str:
        client = RetryingHttpClient(
            timeout_seconds=1,
            max_attempts=1,
            user_agent="test",
        )

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, request=request)

        await client.client.aclose()
        client.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            await client.get(
                "https://example.invalid",
                params={"apikey": "do-not-expose"},
            )
        except ProviderRequestError as error:
            return str(error)
        raise AssertionError("Expected ProviderRequestError")

    message = asyncio.run(run())
    assert "do-not-expose" not in message
