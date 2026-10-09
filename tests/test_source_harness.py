from datetime import date

import pytest

from sp500_candidate_engine.source_harness import (
    CandidateCollectionPlan,
    SourceLimitViolation,
    SourcePolicies,
    validate_candidate_collection_plan,
)


def test_source_policies_encode_required_free_plan_limits() -> None:
    policies = SourcePolicies()
    assert policies.massive_plan == "stocks_basic"
    assert policies.massive_requests_per_minute == 5
    assert policies.massive_price_timing == "end_of_day"
    assert policies.massive_price_history_years == 2
    assert policies.massive_dividend_history_scope == "free_plan_limited"
    assert policies.massive_news_history_scope == "free_plan_limited"
    assert policies.sec_edgar_json_api_enabled
    assert policies.sec_edgar_bulk_zip_enabled
    assert policies.sec_financial_normalization_required
    assert policies.alpha_vantage_requests_per_day == 25
    assert policies.alpha_vantage_earnings_scope == "all_symbols"


def test_valid_plan_reports_massive_minimum_runtime() -> None:
    result = validate_candidate_collection_plan(
        CandidateCollectionPlan(
            target_date=date(2026, 10, 1),
            evaluated_on=date(2026, 10, 9),
            massive_requests=503,
        ),
        SourcePolicies(),
    )
    massive = result["massive"]
    alpha_vantage = result["alpha_vantage"]
    assert isinstance(massive, dict)
    assert isinstance(alpha_vantage, dict)
    assert massive["minimum_minutes"] == 101
    assert alpha_vantage["requests"] == 1


def test_massive_rejects_price_date_older_than_two_year_window() -> None:
    with pytest.raises(SourceLimitViolation):
        validate_candidate_collection_plan(
            CandidateCollectionPlan(
                target_date=date(2024, 10, 8),
                evaluated_on=date(2026, 10, 9),
                massive_requests=1,
            ),
            SourcePolicies(),
        )


def test_alpha_vantage_rejects_more_than_25_daily_requests() -> None:
    with pytest.raises(SourceLimitViolation):
        validate_candidate_collection_plan(
            CandidateCollectionPlan(
                target_date=date(2026, 10, 1),
                evaluated_on=date(2026, 10, 9),
                massive_requests=1,
                alpha_vantage_requests=26,
            ),
            SourcePolicies(),
        )


def test_alpha_vantage_earnings_uses_all_symbols_request() -> None:
    with pytest.raises(SourceLimitViolation):
        validate_candidate_collection_plan(
            CandidateCollectionPlan(
                target_date=date(2026, 10, 1),
                evaluated_on=date(2026, 10, 9),
                massive_requests=1,
                alpha_vantage_symbol_filter="AAPL",
            ),
            SourcePolicies(),
        )


def test_sec_financials_require_normalization() -> None:
    with pytest.raises(SourceLimitViolation):
        validate_candidate_collection_plan(
            CandidateCollectionPlan(
                target_date=date(2026, 10, 1),
                evaluated_on=date(2026, 10, 9),
                massive_requests=1,
                collect_sec_financials=True,
                normalize_sec_financials=False,
            ),
            SourcePolicies(),
        )
