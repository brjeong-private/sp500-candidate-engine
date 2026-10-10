from datetime import date, datetime

from sp500_candidate_engine.backfill import (
    backfill_cutoff,
    build_backfill_plan,
    filter_available_supplements,
    xnyse_sessions,
)
from sp500_candidate_engine.models import UTC
from sp500_candidate_engine.production_models import CorporateAction, NewsItem
from sp500_candidate_engine.source_harness import SourcePolicies


def test_xnys_sessions_exclude_weekends_and_labor_day() -> None:
    sessions = xnyse_sessions(date(2026, 7, 9), date(2026, 10, 8))
    assert len(sessions) == 65
    assert date(2026, 9, 7) not in sessions
    assert sessions[0] == date(2026, 7, 9)
    assert sessions[-1] == date(2026, 10, 8)


def test_backfill_plan_avoids_alpha_historical_calls() -> None:
    plan = build_backfill_plan(
        start_date=date(2026, 7, 9),
        end_date=date(2026, 10, 8),
        evaluated_on=date(2026, 10, 9),
        policies=SourcePolicies(),
    )
    assert len(plan.sessions) == 65
    assert plan.massive_price_requests == 65
    assert plan.massive_action_base_requests == 9
    assert plan.massive_news_chunk_requests == 14
    assert plan.massive_base_requests == 88
    assert plan.massive_minimum_minutes == 18
    assert plan.alpha_vantage_requests == 0
    assert plan.knowledge_mode == "HISTORICAL_RECONSTRUCTION"


def test_backfill_cutoff_is_next_day_0530_new_york() -> None:
    assert backfill_cutoff(date(2026, 10, 8)) == datetime(2026, 10, 9, 9, 30, tzinfo=UTC)


def test_future_supplements_are_excluded_from_daily_snapshot() -> None:
    cutoff = datetime(2026, 10, 9, 9, 30, tzinfo=UTC)
    previous_cutoff = datetime(2026, 10, 8, 9, 30, tzinfo=UTC)
    visible_action = CorporateAction(
        provider_action_id="visible",
        symbol="AAPL",
        action_type="DIVIDEND",
        effective_date=date(2026, 10, 20),
        declaration_date=date(2026, 10, 8),
        record_date=None,
        pay_date=None,
        cash_amount=0.25,
        currency="USD",
        split_from=None,
        split_to=None,
        source_available_at=datetime(2026, 10, 8, 12, 0, tzinfo=UTC),
        metadata={"id": "visible"},
    )
    future_action = CorporateAction(
        provider_action_id="future",
        symbol="AAPL",
        action_type="DIVIDEND",
        effective_date=date(2026, 10, 20),
        declaration_date=date(2026, 10, 9),
        record_date=None,
        pay_date=None,
        cash_amount=0.25,
        currency="USD",
        split_from=None,
        split_to=None,
        source_available_at=datetime(2026, 10, 9, 10, 0, tzinfo=UTC),
        metadata={"id": "future"},
    )
    visible_news = NewsItem(
        provider_event_id="visible-news",
        title="Visible",
        article_url="https://example.com/visible",
        published_at=datetime(2026, 10, 9, 9, 0, tzinfo=UTC),
        tickers=("AAPL",),
        metadata={"id": "visible-news"},
    )
    future_news = NewsItem(
        provider_event_id="future-news",
        title="Future",
        article_url="https://example.com/future",
        published_at=datetime(2026, 10, 9, 10, 0, tzinfo=UTC),
        tickers=("AAPL",),
        metadata={"id": "future-news"},
    )
    old_news = NewsItem(
        provider_event_id="old-news",
        title="Old",
        article_url="https://example.com/old",
        published_at=datetime(2026, 10, 8, 9, 0, tzinfo=UTC),
        tickers=("AAPL",),
        metadata={"id": "old-news"},
    )
    actions, news = filter_available_supplements(
        actions=(visible_action, future_action),
        news=(old_news, visible_news, future_news),
        cutoff_at=cutoff,
        after_at=previous_cutoff,
    )
    assert [item.provider_action_id for item in actions] == ["visible"]
    assert [item.provider_event_id for item in news] == ["visible-news"]
