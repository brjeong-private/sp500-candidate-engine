from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Literal
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")
LLM_DAY_BOUNDARY_VERSION = "llm-ny-day-0530-v1"


@dataclass(frozen=True)
class PublicationBound:
    local_date: date
    precision: Literal["DAY", "TIMESTAMP"]
    upper_bound_at: datetime


def llm_cutoff(cutoff_at: datetime) -> datetime:
    if cutoff_at.utcoffset() is None:
        raise ValueError("LLM cutoff must be timezone-aware")
    local = cutoff_at.astimezone(NEW_YORK)
    scheduled = datetime.combine(local.date(), time(5, 30), NEW_YORK)
    return min(cutoff_at, scheduled).astimezone(UTC)


def publication_bound(value: object, cutoff_at: datetime) -> PublicationBound:
    """LLM-only: earlier NY dates need no time; today's sources require a precise time."""
    effective = llm_cutoff(cutoff_at)
    reference_date = effective.astimezone(NEW_YORK).date()
    if isinstance(value, str):
        value = date.fromisoformat(value) if len(value) == 10 else datetime.fromisoformat(value)
    if isinstance(value, datetime):
        if value.utcoffset() is None:
            raise ValueError("LLM publication timestamp requires a timezone")
        local_date = value.astimezone(NEW_YORK).date()
    elif isinstance(value, date):
        local_date = value
    else:
        raise ValueError("LLM publication requires a trustworthy date or timestamp")
    if local_date < reference_date:
        # This is a day upper bound, not an invented publication time.
        upper = datetime.combine(local_date, time.max, NEW_YORK).astimezone(UTC)
        return PublicationBound(local_date, "DAY", upper)
    if local_date > reference_date:
        raise ValueError("LLM publication date exceeds the NY cutoff analysis day")
    if not isinstance(value, datetime):
        raise ValueError("LLM current-day publication requires a precise timestamp")
    if value >= effective:
        raise ValueError("LLM current-day publication must be before the 05:30 New York cutoff")
    return PublicationBound(local_date, "TIMESTAMP", value.astimezone(UTC))
