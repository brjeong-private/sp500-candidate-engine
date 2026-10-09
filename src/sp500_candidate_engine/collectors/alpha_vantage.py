from __future__ import annotations

import csv
import io
from datetime import date, datetime

from sp500_candidate_engine.http import RetryingHttpClient
from sp500_candidate_engine.models import UTC
from sp500_candidate_engine.production_models import (
    AlphaEarningsCollection,
    EarningsEvent,
)


def _date_or_none(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def _float_or_none(value: str | None) -> float | None:
    if not value:
        return None
    return float(value)


class AlphaVantageEarningsCollector:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout_seconds: float,
        max_attempts: int,
        user_agent: str,
    ) -> None:
        if not api_key:
            raise ValueError("ALPHA_VANTAGE_API_KEY is required")
        self.base_url = base_url
        self.api_key = api_key
        self.client = RetryingHttpClient(
            timeout_seconds=timeout_seconds,
            max_attempts=max_attempts,
            user_agent=user_agent,
        )

    async def __aenter__(self) -> AlphaVantageEarningsCollector:
        await self.client.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: object,
        exc: object,
        traceback: object,
    ) -> None:
        await self.client.__aexit__(exc_type, exc, traceback)

    async def collect(self, horizon: str = "3month") -> AlphaEarningsCollection:
        response = await self.client.get(
            self.base_url,
            params={
                "function": "EARNINGS_CALENDAR",
                "horizon": horizon,
                "apikey": self.api_key,
            },
        )
        content_type = response.headers.get("content-type", "")
        if "json" in content_type:
            payload = response.json()
            raise ValueError(
                f"Alpha Vantage returned JSON instead of earnings CSV; "
                f"message={payload.get('Information') or payload.get('Note') or 'unknown'}"
            )
        observed_at = datetime.now(UTC)
        rows = list(csv.DictReader(io.StringIO(response.text)))
        events: list[EarningsEvent] = []
        for row in rows:
            report_date = _date_or_none(row.get("reportDate"))
            symbol = (row.get("symbol") or "").strip()
            if report_date is None or not symbol:
                continue
            events.append(
                EarningsEvent(
                    symbol=symbol,
                    company_name=(row.get("name") or "").strip() or None,
                    report_date=report_date,
                    fiscal_date_ending=_date_or_none(row.get("fiscalDateEnding")),
                    estimate=_float_or_none(row.get("estimate")),
                    currency=(row.get("currency") or "").strip() or None,
                    time_of_day=(row.get("timeOfTheDay") or "").strip() or None,
                    observed_at=observed_at,
                )
            )
        return AlphaEarningsCollection(
            observed_at=observed_at,
            events=tuple(events),
            payload={"horizon": horizon, "rows": rows},
        )

    async def probe(self) -> dict[str, object]:
        collection = await self.collect()
        return {
            "events": len(collection.events),
            "observed_at": collection.observed_at.isoformat(),
        }
