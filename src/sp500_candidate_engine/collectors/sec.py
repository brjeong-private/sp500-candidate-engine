from __future__ import annotations

from datetime import datetime

from sp500_candidate_engine.http import IntervalRateLimiter, RetryingHttpClient
from sp500_candidate_engine.models import UTC
from sp500_candidate_engine.production_models import SecCompany, SecReferenceCollection

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
SEC_SUBMISSIONS_ZIP_URL = "https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip"
SEC_COMPANYFACTS_ZIP_URL = "https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip"


class SecCollector:
    def __init__(
        self,
        *,
        timeout_seconds: float,
        max_attempts: int,
        user_agent: str,
        requests_per_second: int = 5,
    ) -> None:
        if "@" not in user_agent:
            raise ValueError("SEC User-Agent must contain a contact email")
        self.client = RetryingHttpClient(
            timeout_seconds=timeout_seconds,
            max_attempts=max_attempts,
            user_agent=user_agent,
            limiter=IntervalRateLimiter(requests_per_second * 60),
        )

    async def __aenter__(self) -> SecCollector:
        await self.client.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: object,
        exc: object,
        traceback: object,
    ) -> None:
        await self.client.__aexit__(exc_type, exc, traceback)

    async def collect_reference(self) -> SecReferenceCollection:
        response = await self.client.get(SEC_TICKERS_URL)
        payload = response.json()
        fields = payload.get("fields") or []
        data = payload.get("data") or []
        if not isinstance(fields, list) or not isinstance(data, list):
            raise ValueError("SEC company ticker response has an invalid shape")
        index = {str(field): position for position, field in enumerate(fields)}
        required = {"cik", "name", "ticker", "exchange"}
        missing = required - index.keys()
        if missing:
            raise ValueError(f"SEC company ticker response is missing fields: {sorted(missing)}")
        companies: list[SecCompany] = []
        for row in data:
            if not isinstance(row, list):
                continue
            exchange = row[index["exchange"]]
            companies.append(
                SecCompany(
                    cik=str(row[index["cik"]]).zfill(10),
                    name=str(row[index["name"]]),
                    ticker=str(row[index["ticker"]]),
                    exchange=str(exchange) if exchange else None,
                )
            )
        observed_at = datetime.now(UTC)
        return SecReferenceCollection(
            observed_at=observed_at,
            companies=tuple(companies),
            payload={"fields": fields, "data": data},
        )

    async def download_bulk(self, dataset: str) -> bytes:
        urls = {
            "sec_submissions_bulk": SEC_SUBMISSIONS_ZIP_URL,
            "sec_companyfacts_bulk": SEC_COMPANYFACTS_ZIP_URL,
        }
        try:
            url = urls[dataset]
        except KeyError as error:
            raise ValueError(f"Unsupported SEC bulk dataset: {dataset}") from error
        response = await self.client.get(url)
        if not response.content.startswith(b"PK"):
            raise ValueError(f"SEC bulk dataset is not a ZIP file: {dataset}")
        return response.content

    async def probe(self) -> dict[str, object]:
        collection = await self.collect_reference()
        return {
            "companies": len(collection.companies),
            "observed_at": collection.observed_at.isoformat(),
        }
