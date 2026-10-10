from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from sp500_candidate_engine.models import DailyBar


@dataclass(frozen=True)
class CorporateAction:
    provider_action_id: str
    symbol: str
    action_type: str
    effective_date: date
    declaration_date: date | None
    record_date: date | None
    pay_date: date | None
    cash_amount: float | None
    currency: str | None
    split_from: float | None
    split_to: float | None
    source_available_at: datetime
    metadata: dict[str, object]


@dataclass(frozen=True)
class NewsItem:
    provider_event_id: str
    title: str
    article_url: str
    published_at: datetime
    tickers: tuple[str, ...]
    metadata: dict[str, object]


@dataclass(frozen=True)
class MassiveCollection:
    observed_at: datetime
    source_available_at: datetime
    bars: tuple[DailyBar, ...]
    benchmark_bars: tuple[DailyBar, ...]
    actions: tuple[CorporateAction, ...]
    news: tuple[NewsItem, ...]
    payloads: dict[str, dict[str, object]]


@dataclass(frozen=True)
class MassiveBackfillRange:
    observed_at: datetime
    actions: tuple[CorporateAction, ...]
    news: tuple[NewsItem, ...]
    payloads: dict[str, dict[str, object]]


@dataclass(frozen=True)
class SecCompany:
    cik: str
    name: str
    ticker: str
    exchange: str | None


@dataclass(frozen=True)
class SecReferenceCollection:
    observed_at: datetime
    companies: tuple[SecCompany, ...]
    payload: dict[str, object]


@dataclass(frozen=True)
class EarningsEvent:
    symbol: str
    company_name: str | None
    report_date: date
    fiscal_date_ending: date | None
    estimate: float | None
    currency: str | None
    time_of_day: str | None
    observed_at: datetime


@dataclass(frozen=True)
class AlphaEarningsCollection:
    observed_at: datetime
    events: tuple[EarningsEvent, ...]
    payload: dict[str, object]
