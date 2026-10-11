from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from backend.app.schemas.common import ReadModel
from backend.app.schemas.common import UTCDateTime as datetime


class Dataset(StrEnum):
    DAILY_BARS = "daily-bars"
    CORPORATE_ACTIONS = "corporate-actions"
    NEWS = "news"
    SEC_FILINGS = "sec-filings"
    SEC_FACTS = "sec-facts"
    EARNINGS = "earnings"
    UNIVERSE_MEMBERS = "universe-members"
    EXCHANGE_SESSIONS = "exchange-sessions"


class Provenance(ReadModel):
    source_snapshot_id: UUID
    source_id: int
    source_code: str
    source_available_at: datetime
    observed_at: datetime
    revision_no: int | None = None


class InstrumentRecord(Provenance):
    instrument_id: UUID
    issuer_id: UUID
    ticker: str | None


class DailyBar(InstrumentRecord):
    dataset: Literal["daily-bars"] = "daily-bars"
    session_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    adjusted_close: Decimal | None
    volume: int
    vwap: Decimal | None
    currency: str
    source_timestamp: datetime
    price_adjustment_status: str
    volume_adjustment_status: str


class CorporateAction(InstrumentRecord):
    dataset: Literal["corporate-actions"] = "corporate-actions"
    action_id: UUID
    action_type: Literal["DIVIDEND", "SPLIT"]
    effective_date: date
    declaration_date: date | None
    record_date: date | None
    pay_date: date | None
    cash_amount: Decimal | None
    currency: str | None
    split_from: Decimal | None
    split_to: Decimal | None


class EventRecord(Provenance):
    event_id: UUID
    event_revision_id: UUID
    instrument_id: UUID | None
    issuer_id: UUID | None
    ticker: str | None
    title: str
    status: str | None
    scheduled_at: datetime | None
    published_at: datetime | None


class News(EventRecord):
    dataset: Literal["news"] = "news"
    event_type: Literal["NEWS"]


class Earnings(EventRecord):
    dataset: Literal["earnings"] = "earnings"
    event_type: Literal["EARNINGS"]


class SecFiling(Provenance):
    dataset: Literal["sec-filings"] = "sec-filings"
    filing_id: UUID
    issuer_id: UUID
    accession_no: str
    form_type: str
    period_end: date | None
    filed_date: date
    accepted_at: datetime
    is_amendment: bool


class SecFact(Provenance):
    dataset: Literal["sec-facts"] = "sec-facts"
    fact_id: UUID
    filing_id: UUID
    issuer_id: UUID
    taxonomy: str
    concept: str
    unit: str
    period_start: date | None
    period_end: date
    value_numeric: Decimal | None
    decimals: int | None
    fiscal_year: int | None
    fiscal_period: str | None
    frame: str | None


class UniverseMember(InstrumentRecord):
    dataset: Literal["universe-members"] = "universe-members"
    universe_version_id: UUID
    universe_id: UUID
    universe_code: str
    as_of_date: date
    provider_revision_id: str
    announced_at: datetime
    effective_at: datetime
    security_name: str
    sector: str | None
    sub_industry: str | None
    provider_symbol: str


class ExchangeSession(Provenance):
    dataset: Literal["exchange-sessions"] = "exchange-sessions"
    calendar_version: str
    exchange_mic: str
    session_date: date
    open_at: datetime
    close_at: datetime
    is_early_close: bool
    status: Literal["OPEN", "CLOSED", "SPECIAL"]


CollectionRecord = Annotated[
    DailyBar
    | CorporateAction
    | News
    | SecFiling
    | SecFact
    | Earnings
    | UniverseMember
    | ExchangeSession,
    Field(discriminator="dataset"),
]
