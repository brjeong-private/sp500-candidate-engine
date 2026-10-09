from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta

import exchange_calendars

from sp500_candidate_engine.models import NEW_YORK, UTC
from sp500_candidate_engine.production_models import CorporateAction, NewsItem
from sp500_candidate_engine.source_harness import (
    CandidateCollectionPlan,
    SourcePolicies,
    validate_candidate_collection_plan,
)


@dataclass(frozen=True)
class BackfillPlan:
    start_date: date
    end_date: date
    sessions: tuple[date, ...]
    massive_price_requests: int
    massive_action_base_requests: int
    massive_news_chunk_requests: int
    massive_base_requests: int
    massive_minimum_minutes: int
    sec_requests: int
    alpha_vantage_requests: int
    knowledge_mode: str
    required_changes: tuple[str, ...]
    accepted_gaps: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["start_date"] = self.start_date.isoformat()
        payload["end_date"] = self.end_date.isoformat()
        payload["sessions"] = [session.isoformat() for session in self.sessions]
        return payload


def xnyse_sessions(start_date: date, end_date: date) -> tuple[date, ...]:
    if start_date > end_date:
        raise ValueError("start_date must be on or before end_date")
    calendar = exchange_calendars.get_calendar("XNYS")
    sessions = calendar.sessions_in_range(
        start_date.isoformat(),
        end_date.isoformat(),
    )
    return tuple(timestamp.date() for timestamp in sessions)


def backfill_cutoff(session_date: date) -> datetime:
    return datetime.combine(
        session_date + timedelta(days=1),
        time(hour=5, minute=30),
        tzinfo=NEW_YORK,
    ).astimezone(UTC)


def previous_backfill_cutoff(session_date: date) -> datetime:
    calendar = exchange_calendars.get_calendar("XNYS")
    previous_session = calendar.previous_session(session_date.isoformat())
    return backfill_cutoff(previous_session.date())


def filter_available_supplements(
    *,
    actions: tuple[CorporateAction, ...],
    news: tuple[NewsItem, ...],
    cutoff_at: datetime,
    after_at: datetime | None = None,
) -> tuple[tuple[CorporateAction, ...], tuple[NewsItem, ...]]:
    visible_actions = tuple(
        action
        for action in actions
        if action.source_available_at <= cutoff_at
        and (after_at is None or action.source_available_at > after_at)
    )
    visible_news = tuple(
        item
        for item in news
        if item.published_at <= cutoff_at and (after_at is None or item.published_at > after_at)
    )
    return visible_actions, visible_news


def build_backfill_plan(
    *,
    start_date: date,
    end_date: date,
    evaluated_on: date,
    policies: SourcePolicies,
    news_chunk_days: int = 7,
) -> BackfillPlan:
    if news_chunk_days <= 0:
        raise ValueError("news_chunk_days must be positive")
    sessions = xnyse_sessions(start_date, end_date)
    if not sessions:
        raise ValueError("No XNYS sessions found in the requested range")
    calendar_days = (end_date - start_date).days + 1
    news_chunks = math.ceil(calendar_days / news_chunk_days)
    price_requests = len(sessions)
    action_requests = 2
    base_requests = price_requests + action_requests + news_chunks
    harness = validate_candidate_collection_plan(
        CandidateCollectionPlan(
            target_date=start_date,
            evaluated_on=evaluated_on,
            massive_requests=base_requests,
            alpha_vantage_requests=0,
            alpha_vantage_symbol_filter=None,
            collect_sec_financials=True,
            normalize_sec_financials=True,
        ),
        policies,
    )
    massive = harness["massive"]
    if not isinstance(massive, dict):
        raise TypeError("Massive harness result must be a dictionary")
    return BackfillPlan(
        start_date=start_date,
        end_date=end_date,
        sessions=sessions,
        massive_price_requests=price_requests,
        massive_action_base_requests=action_requests,
        massive_news_chunk_requests=news_chunks,
        massive_base_requests=base_requests,
        massive_minimum_minutes=int(massive["minimum_minutes"]),
        sec_requests=3,
        alpha_vantage_requests=0,
        knowledge_mode="HISTORICAL_RECONSTRUCTION",
        required_changes=(
            "Use staging COPY and set-based merge for PostgreSQL",
            "Advance dataset checkpoints after committed ranges",
            "Add official exchange calendar and halt snapshots",
            "Replace Wikipedia history with licensed point-in-time S&P data",
        ),
        accepted_gaps=(
            "Alpha Vantage cannot reconstruct historical earnings revisions",
            "Wikipedia universe is not official point-in-time S&P DJI history",
            "Massive Basic historical dividend and news depth is plan-limited",
        ),
    )
