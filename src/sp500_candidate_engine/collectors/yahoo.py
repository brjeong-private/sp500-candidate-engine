from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from sp500_candidate_engine.http import RetryingHttpClient
from sp500_candidate_engine.models import (
    NEW_YORK,
    UTC,
    DailyBar,
    MarketCollection,
    RunSpec,
    UniverseMember,
)
from sp500_candidate_engine.temporal import FutureDataViolation, TemporalFence

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"


class YahooDailyBarCollector:
    def __init__(
        self,
        client: RetryingHttpClient,
        *,
        max_concurrency: int,
        min_success_ratio: float,
    ) -> None:
        self.client = client
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.min_success_ratio = min_success_ratio

    async def collect(
        self,
        run_spec: RunSpec,
        members: tuple[UniverseMember, ...],
    ) -> MarketCollection:
        tasks = [self._collect_one(run_spec, member) for member in members]
        results = await asyncio.gather(*tasks)
        bars: list[DailyBar] = []
        failures: dict[str, str] = {}
        payload_rows: list[dict[str, object]] = []
        observed_times: list[datetime] = []

        for member, result in zip(members, results, strict=True):
            if isinstance(result, str):
                failures[member.symbol] = result
                continue
            bar, observed_at = result
            bars.append(bar)
            observed_times.append(observed_at)
            payload_rows.append(
                {
                    "symbol": bar.symbol,
                    "provider_symbol": bar.provider_symbol,
                    "session_date": bar.session_date.isoformat(),
                    "source_timestamp": bar.source_timestamp.isoformat(),
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "adjusted_close": bar.adjusted_close,
                    "volume": bar.volume,
                    "vwap": bar.vwap,
                    "price_adjustment_status": bar.price_adjustment_status,
                    "volume_adjustment_status": bar.volume_adjustment_status,
                }
            )

        success_ratio = len(bars) / len(members)
        if success_ratio < self.min_success_ratio:
            raise ValueError(
                f"Market collection success ratio {success_ratio:.3f} is below "
                f"{self.min_success_ratio:.3f}; failures={len(failures)}"
            )

        source_available_at = datetime.combine(
            run_spec.target_date,
            datetime.min.time().replace(hour=16, minute=15),
            tzinfo=NEW_YORK,
        ).astimezone(UTC)
        TemporalFence(run_spec).require_source_available(source_available_at)
        observed_at = max(observed_times)
        return MarketCollection(
            observed_at=observed_at,
            source_available_at=source_available_at,
            bars=tuple(sorted(bars, key=lambda item: item.symbol)),
            benchmark_bars=(),
            failures=failures,
            sanitized_payload={
                "target_date": run_spec.target_date.isoformat(),
                "request_end_exclusive": run_spec.request_end_exclusive.isoformat(),
                "bars": sorted(payload_rows, key=lambda item: str(item["symbol"])),
                "failures": failures,
            },
        )

    async def _collect_one(
        self, run_spec: RunSpec, member: UniverseMember
    ) -> tuple[DailyBar, datetime] | str:
        async with self.semaphore:
            try:
                response = await self.client.get(
                    CHART_URL.format(symbol=member.provider_symbol),
                    params={
                        "period1": int(run_spec.request_start.timestamp()),
                        "period2": int(run_spec.request_end_exclusive.timestamp()),
                        "interval": "1d",
                        "events": "div,splits",
                        "includeAdjustedClose": "true",
                    },
                )
                observed_at = datetime.now(UTC)
                bar = self._parse_bar(response, run_spec, member)
                TemporalFence(run_spec).validate_record(
                    session_date=bar.session_date,
                    source_available_at=datetime.combine(
                        run_spec.target_date,
                        datetime.min.time().replace(hour=16, minute=15),
                        tzinfo=NEW_YORK,
                    ).astimezone(UTC),
                    observed_at=observed_at,
                )
                return bar, observed_at
            except FutureDataViolation:
                raise
            except (httpx.HTTPError, KeyError, TypeError, ValueError, IndexError) as error:
                return f"{type(error).__name__}: {error}"

    @staticmethod
    def _parse_bar(
        response: httpx.Response,
        run_spec: RunSpec,
        member: UniverseMember,
    ) -> DailyBar:
        payload = response.json()
        chart = payload["chart"]
        if chart.get("error"):
            raise ValueError(str(chart["error"]))
        result = chart["result"][0]
        timezone_name = result.get("meta", {}).get("exchangeTimezoneName", "America/New_York")
        exchange_tz = ZoneInfo(timezone_name)
        timestamps = result.get("timestamp") or []
        quote = result["indicators"]["quote"][0]
        adjusted = (result["indicators"].get("adjclose") or [{}])[0].get("adjclose", [])
        fence = TemporalFence(run_spec)

        selected_index: int | None = None
        selected_timestamp: datetime | None = None
        for index, value in enumerate(timestamps):
            source_timestamp = datetime.fromtimestamp(value, tz=UTC)
            session_date = source_timestamp.astimezone(exchange_tz).date()
            fence.require_session_date(session_date, field=f"{member.symbol}.session_date")
            if session_date == run_spec.target_date:
                selected_index = index
                selected_timestamp = source_timestamp

        if selected_index is None or selected_timestamp is None:
            raise ValueError(f"No bar returned for {run_spec.target_date.isoformat()}")

        values = {
            "open": quote["open"][selected_index],
            "high": quote["high"][selected_index],
            "low": quote["low"][selected_index],
            "close": quote["close"][selected_index],
            "volume": quote["volume"][selected_index],
        }
        if any(value is None for value in values.values()):
            raise ValueError("Daily bar contains null OHLCV")
        open_value = float(values["open"])
        high_value = float(values["high"])
        low_value = float(values["low"])
        close_value = float(values["close"])
        volume_value = int(values["volume"])
        if low_value > high_value or not low_value <= open_value <= high_value:
            raise ValueError("Invalid OHLC range")
        if not low_value <= close_value <= high_value or volume_value < 0:
            raise ValueError("Invalid close or volume")
        adjusted_value = (
            float(adjusted[selected_index])
            if selected_index < len(adjusted) and adjusted[selected_index] is not None
            else None
        )
        return DailyBar(
            symbol=member.symbol,
            provider_symbol=member.provider_symbol,
            session_date=run_spec.target_date,
            source_timestamp=selected_timestamp,
            open=open_value,
            high=high_value,
            low=low_value,
            close=close_value,
            adjusted_close=adjusted_value,
            volume=volume_value,
            vwap=None,
            price_adjustment_status="UNADJUSTED_WITH_ADJUSTED_CLOSE",
            volume_adjustment_status="UNADJUSTED",
        )
