from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sp500_candidate_engine.http import IntervalRateLimiter, RetryingHttpClient
from sp500_candidate_engine.models import (
    NEW_YORK,
    UTC,
    DailyBar,
    KnowledgeMode,
    MarketCollection,
    RunSpec,
    UniverseMember,
)
from sp500_candidate_engine.production_models import (
    CorporateAction,
    MassiveBackfillRange,
    MassiveCollection,
    NewsItem,
)
from sp500_candidate_engine.temporal import TemporalFence


def _date_or_none(value: object) -> date | None:
    if not value:
        return None
    return date.fromisoformat(str(value)[:10])


def _float_or_none(value: object) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


class MassiveCollector:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout_seconds: float,
        max_attempts: int,
        user_agent: str,
        requests_per_minute: int,
    ) -> None:
        if not api_key:
            raise ValueError("MASSIVE_API_KEY is required")
        self.base_url = base_url.rstrip("/")
        self.client = RetryingHttpClient(
            timeout_seconds=timeout_seconds,
            max_attempts=max_attempts,
            user_agent=user_agent,
            headers={"Authorization": f"Bearer {api_key}"},
            limiter=IntervalRateLimiter(requests_per_minute),
        )

    async def __aenter__(self) -> MassiveCollector:
        await self.client.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: object,
        exc: object,
        traceback: object,
    ) -> None:
        await self.client.__aexit__(exc_type, exc, traceback)

    async def collect(
        self,
        run_spec: RunSpec,
        members: tuple[UniverseMember, ...],
    ) -> MassiveCollection:
        symbols = {
            provider_symbol: member.symbol
            for member in members
            for provider_symbol in {member.symbol, member.provider_symbol}
        }
        market = await self.collect_grouped_daily(run_spec, members)
        dividends = await self._collect_pages(
            "/v3/reference/dividends",
            params={
                "ex_dividend_date.gte": (run_spec.target_date - timedelta(days=7)).isoformat(),
                "ex_dividend_date.lte": (run_spec.target_date + timedelta(days=90)).isoformat(),
                "limit": 1000,
                "sort": "ex_dividend_date",
            },
        )
        splits = await self._collect_pages(
            "/v3/reference/splits",
            params={
                "execution_date": run_spec.target_date.isoformat(),
                "limit": 1000,
                "sort": "execution_date",
            },
        )
        news = await self._collect_pages(
            "/v2/reference/news",
            params={
                "published_utc.gte": run_spec.request_start.astimezone(UTC).isoformat(),
                "published_utc.lt": run_spec.request_end_exclusive.astimezone(UTC).isoformat(),
                "limit": 1000,
                "sort": "published_utc",
                "order": "asc",
            },
        )
        observed_at = datetime.now(UTC)
        source_available_at = datetime.combine(
            run_spec.target_date,
            time(hour=16, minute=15),
            tzinfo=NEW_YORK,
        ).astimezone(UTC)
        actions = self._parse_actions(dividends, splits, run_spec, symbols)
        news_items = self._parse_news(news, run_spec, symbols)
        return MassiveCollection(
            observed_at=observed_at,
            source_available_at=source_available_at,
            bars=market.bars,
            actions=actions,
            news=news_items,
            payloads={
                "massive_grouped_daily": {
                    "target_date": run_spec.target_date.isoformat(),
                    "results": market.sanitized_payload["results"],
                },
                "massive_dividends": {"results": dividends},
                "massive_splits": {"results": splits},
                "massive_news": {"results": news},
            },
        )

    async def collect_grouped_daily(
        self,
        run_spec: RunSpec,
        members: tuple[UniverseMember, ...],
    ) -> MarketCollection:
        symbols = {
            provider_symbol: member.symbol
            for member in members
            for provider_symbol in {member.symbol, member.provider_symbol}
        }
        grouped = await self._get_json(
            f"/v2/aggs/grouped/locale/us/market/stocks/{run_spec.target_date.isoformat()}",
            params={"adjusted": "false", "include_otc": "false"},
        )
        observed_at = datetime.now(UTC)
        source_available_at = datetime.combine(
            run_spec.target_date,
            time(hour=16, minute=15),
            tzinfo=NEW_YORK,
        ).astimezone(UTC)
        bars = self._parse_grouped(grouped, run_spec, symbols)
        returned = {bar.symbol for bar in bars}
        failures = {
            member.symbol: "No Massive grouped daily bar returned"
            for member in members
            if member.symbol not in returned
        }
        return MarketCollection(
            observed_at=observed_at,
            source_available_at=source_available_at,
            bars=bars,
            failures=failures,
            sanitized_payload={
                "target_date": run_spec.target_date.isoformat(),
                "results": grouped.get("results", []),
            },
        )

    async def collect_backfill_range(
        self,
        *,
        start_date: date,
        end_date: date,
        members: tuple[UniverseMember, ...],
        news_chunk_days: int = 7,
    ) -> MassiveBackfillRange:
        if start_date > end_date:
            raise ValueError("start_date must be on or before end_date")
        if news_chunk_days <= 0:
            raise ValueError("news_chunk_days must be positive")
        symbols = {
            provider_symbol: member.symbol
            for member in members
            for provider_symbol in {member.symbol, member.provider_symbol}
        }
        dividends = await self._collect_pages(
            "/v3/reference/dividends",
            params={
                "ex_dividend_date.gte": start_date.isoformat(),
                "ex_dividend_date.lte": (end_date + timedelta(days=90)).isoformat(),
                "limit": 1000,
                "sort": "ex_dividend_date",
            },
        )
        splits = await self._collect_pages(
            "/v3/reference/splits",
            params={
                "execution_date.gte": start_date.isoformat(),
                "execution_date.lte": end_date.isoformat(),
                "limit": 1000,
                "sort": "execution_date",
            },
        )
        news_rows: list[dict[str, object]] = []
        news_chunks: list[dict[str, object]] = []
        start_at = datetime.combine(start_date, time.min, tzinfo=NEW_YORK).astimezone(UTC)
        range_end_at = datetime.combine(
            end_date + timedelta(days=1),
            time(hour=5, minute=30),
            tzinfo=NEW_YORK,
        ).astimezone(UTC)
        while start_at < range_end_at:
            end_at = min(range_end_at, start_at + timedelta(days=news_chunk_days))
            rows = await self._collect_pages(
                "/v2/reference/news",
                params={
                    "published_utc.gte": start_at.isoformat(),
                    "published_utc.lt": end_at.isoformat(),
                    "limit": 1000,
                    "sort": "published_utc",
                    "order": "asc",
                },
            )
            news_rows.extend(rows)
            news_chunks.append(
                {
                    "start_at": start_at.isoformat(),
                    "end_at": end_at.isoformat(),
                    "results": rows,
                }
            )
            start_at = end_at
        cutoff_at = datetime.combine(
            end_date + timedelta(days=1),
            time(hour=5, minute=30),
            tzinfo=NEW_YORK,
        ).astimezone(UTC)
        range_spec = RunSpec(
            target_date=end_date,
            cutoff_at=cutoff_at,
            knowledge_mode=KnowledgeMode.HISTORICAL_RECONSTRUCTION,
        )
        actions = self._parse_actions(
            dividends,
            splits,
            range_spec,
            symbols,
            effective_start=start_date,
            effective_end=end_date,
            knowledge_date=end_date,
        )
        news = self._parse_news(news_rows, range_spec, symbols)
        return MassiveBackfillRange(
            observed_at=datetime.now(UTC),
            actions=actions,
            news=news,
            payloads={
                "massive_dividends_backfill": {"results": dividends},
                "massive_splits_backfill": {"results": splits},
                "massive_news_backfill": {"chunks": news_chunks},
            },
        )

    async def probe(self, target_date: date) -> dict[str, object]:
        payload = await self._get_json(
            f"/v2/aggs/grouped/locale/us/market/stocks/{target_date.isoformat()}",
            params={"adjusted": "false", "include_otc": "false"},
        )
        return {
            "status": payload.get("status"),
            "query_count": payload.get("queryCount"),
            "results_count": payload.get("resultsCount"),
            "target_date": target_date.isoformat(),
        }

    async def _get_json(
        self,
        path_or_url: str,
        *,
        params: dict[str, str | int] | None = None,
    ) -> dict[str, object]:
        url = path_or_url if path_or_url.startswith("http") else f"{self.base_url}{path_or_url}"
        response = await self.client.get(url, params=params)
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Massive response must be a JSON object")
        return payload

    async def _collect_pages(
        self,
        path: str,
        *,
        params: dict[str, str | int],
        max_pages: int = 100,
    ) -> list[dict[str, object]]:
        results: list[dict[str, object]] = []
        next_url: str | None = path
        page = 0
        next_params: dict[str, str | int] | None = params
        while next_url:
            page += 1
            if page > max_pages:
                raise ValueError(f"Massive pagination exceeded {max_pages} pages for {path}")
            payload = await self._get_json(next_url, params=next_params)
            page_results = payload.get("results") or []
            if not isinstance(page_results, list):
                raise ValueError(f"Massive results must be a list for {path}")
            results.extend(item for item in page_results if isinstance(item, dict))
            value = payload.get("next_url")
            next_url = str(value) if value else None
            next_params = None
        return results

    @staticmethod
    def _parse_grouped(
        payload: dict[str, object],
        run_spec: RunSpec,
        symbols: dict[str, str],
    ) -> tuple[DailyBar, ...]:
        fence = TemporalFence(run_spec)
        parsed: list[DailyBar] = []
        raw_results = payload.get("results") or []
        if not isinstance(raw_results, list):
            raise ValueError("Massive grouped results must be a list")
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            provider_symbol = str(item.get("T", ""))
            symbol = symbols.get(provider_symbol)
            if symbol is None:
                continue
            timestamp_ms = int(item["t"])
            source_timestamp = datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC)
            session_date = source_timestamp.astimezone(NEW_YORK).date()
            fence.require_session_date(session_date, field=f"{symbol}.session_date")
            if session_date != run_spec.target_date:
                continue
            parsed.append(
                DailyBar(
                    symbol=symbol,
                    provider_symbol=provider_symbol,
                    session_date=session_date,
                    source_timestamp=source_timestamp,
                    open=float(item["o"]),
                    high=float(item["h"]),
                    low=float(item["l"]),
                    close=float(item["c"]),
                    adjusted_close=None,
                    volume=int(item["v"]),
                )
            )
        return tuple(sorted(parsed, key=lambda bar: bar.symbol))

    @staticmethod
    def _parse_actions(
        dividends: list[dict[str, object]],
        splits: list[dict[str, object]],
        run_spec: RunSpec,
        symbols: dict[str, str],
        *,
        effective_start: date | None = None,
        effective_end: date | None = None,
        knowledge_date: date | None = None,
    ) -> tuple[CorporateAction, ...]:
        start_date = effective_start or run_spec.target_date
        end_date = effective_end or run_spec.target_date
        known_by = knowledge_date or run_spec.target_date
        actions: list[CorporateAction] = []
        for item in dividends:
            provider_symbol = str(item.get("ticker", ""))
            symbol = symbols.get(provider_symbol)
            ex_date = _date_or_none(item.get("ex_dividend_date"))
            declaration_date = _date_or_none(item.get("declaration_date"))
            if symbol is None or ex_date is None:
                continue
            if declaration_date is None or declaration_date > known_by:
                continue
            if not start_date <= ex_date <= end_date + timedelta(days=90):
                continue
            actions.append(
                CorporateAction(
                    provider_action_id=str(
                        item.get("id") or f"dividend:{provider_symbol}:{ex_date}"
                    ),
                    symbol=symbol,
                    action_type="DIVIDEND",
                    effective_date=ex_date,
                    declaration_date=declaration_date,
                    record_date=_date_or_none(item.get("record_date")),
                    pay_date=_date_or_none(item.get("pay_date")),
                    cash_amount=_float_or_none(item.get("cash_amount")),
                    currency=str(item.get("currency")) if item.get("currency") else None,
                    split_from=None,
                    split_to=None,
                    source_available_at=datetime.combine(
                        declaration_date, time.min, tzinfo=NEW_YORK
                    ).astimezone(UTC),
                    metadata=item,
                )
            )
        for item in splits:
            provider_symbol = str(item.get("ticker", ""))
            symbol = symbols.get(provider_symbol)
            execution_date = _date_or_none(item.get("execution_date"))
            if (
                symbol is None
                or execution_date is None
                or not start_date <= execution_date <= end_date
            ):
                continue
            actions.append(
                CorporateAction(
                    provider_action_id=str(
                        item.get("id") or f"split:{provider_symbol}:{execution_date}"
                    ),
                    symbol=symbol,
                    action_type="SPLIT",
                    effective_date=execution_date,
                    declaration_date=None,
                    record_date=None,
                    pay_date=None,
                    cash_amount=None,
                    currency=None,
                    split_from=_float_or_none(item.get("split_from")),
                    split_to=_float_or_none(item.get("split_to")),
                    source_available_at=datetime.combine(
                        execution_date,
                        time.min,
                        tzinfo=NEW_YORK,
                    ).astimezone(UTC),
                    metadata=item,
                )
            )
        return tuple(sorted(actions, key=lambda action: (action.symbol, action.action_type)))

    @staticmethod
    def _parse_news(
        rows: list[dict[str, object]],
        run_spec: RunSpec,
        symbols: dict[str, str],
    ) -> tuple[NewsItem, ...]:
        parsed: list[NewsItem] = []
        allowed = set(symbols)
        for item in rows:
            published_value = item.get("published_utc")
            if not published_value:
                continue
            published_at = datetime.fromisoformat(str(published_value).replace("Z", "+00:00"))
            if published_at > run_spec.cutoff_at:
                continue
            tickers_value = item.get("tickers") or []
            tickers = tuple(
                symbols[str(ticker)] for ticker in tickers_value if str(ticker) in allowed
            )
            if not tickers:
                continue
            parsed.append(
                NewsItem(
                    provider_event_id=str(item["id"]),
                    title=str(item.get("title") or ""),
                    article_url=str(item.get("article_url") or ""),
                    published_at=published_at,
                    tickers=tickers,
                    metadata=item,
                )
            )
        return tuple(sorted(parsed, key=lambda news: (news.published_at, news.provider_event_id)))
