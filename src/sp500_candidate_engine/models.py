from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


class KnowledgeMode(StrEnum):
    OPERATIONAL_REPLAY = "OPERATIONAL_REPLAY"
    HISTORICAL_RECONSTRUCTION = "HISTORICAL_RECONSTRUCTION"


@dataclass(frozen=True)
class RunSpec:
    target_date: date
    cutoff_at: datetime
    knowledge_mode: KnowledgeMode

    @classmethod
    def for_date(cls, target_date: date, mode: KnowledgeMode) -> RunSpec:
        local_cutoff = datetime.combine(target_date, time.max, tzinfo=NEW_YORK)
        return cls(target_date, local_cutoff.astimezone(UTC), mode)

    @property
    def request_start(self) -> datetime:
        return datetime.combine(self.target_date, time.min, tzinfo=NEW_YORK)

    @property
    def request_end_exclusive(self) -> datetime:
        return self.request_start + timedelta(days=1)


@dataclass(frozen=True)
class UniverseMember:
    symbol: str
    provider_symbol: str
    security_name: str
    sector: str | None
    sub_industry: str | None
    cik: str | None


@dataclass(frozen=True)
class UniverseCollection:
    revision_id: int
    revision_at: datetime
    source_url: str
    observed_at: datetime
    members: tuple[UniverseMember, ...]
    sanitized_payload: dict[str, object]


@dataclass(frozen=True)
class DailyBar:
    symbol: str
    provider_symbol: str
    session_date: date
    source_timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    adjusted_close: float | None
    volume: int


@dataclass(frozen=True)
class MarketCollection:
    observed_at: datetime
    source_available_at: datetime
    bars: tuple[DailyBar, ...]
    failures: dict[str, str]
    sanitized_payload: dict[str, object]
