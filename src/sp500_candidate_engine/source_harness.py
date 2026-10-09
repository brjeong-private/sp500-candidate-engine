from __future__ import annotations

import calendar
import math
from dataclasses import asdict, dataclass
from datetime import date


class SourceLimitViolation(ValueError):
    """Raised when a planned collection exceeds a configured provider capability."""


@dataclass(frozen=True)
class SourcePolicies:
    massive_plan: str = "stocks_basic"
    massive_requests_per_minute: int = 5
    massive_price_timing: str = "end_of_day"
    massive_price_history_years: int = 2
    massive_dividend_history_scope: str = "free_plan_limited"
    massive_news_history_scope: str = "free_plan_limited"
    sec_edgar_json_api_enabled: bool = True
    sec_edgar_bulk_zip_enabled: bool = True
    sec_financial_normalization_required: bool = True
    alpha_vantage_requests_per_day: int = 25
    alpha_vantage_earnings_scope: str = "all_symbols"

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class CandidateCollectionPlan:
    target_date: date
    evaluated_on: date
    massive_requests: int
    alpha_vantage_requests: int = 1
    alpha_vantage_symbol_filter: str | None = None
    collect_sec_financials: bool = True
    normalize_sec_financials: bool = True


def _years_before(value: date, years: int) -> date:
    year = value.year - years
    day = min(value.day, calendar.monthrange(year, value.month)[1])
    return date(year, value.month, day)


def validate_candidate_collection_plan(
    plan: CandidateCollectionPlan,
    policies: SourcePolicies,
) -> dict[str, object]:
    if plan.massive_requests < 0 or plan.alpha_vantage_requests < 0:
        raise SourceLimitViolation("Provider request counts cannot be negative")
    earliest_massive_date = _years_before(plan.evaluated_on, policies.massive_price_history_years)
    if plan.target_date < earliest_massive_date:
        raise SourceLimitViolation(
            f"Massive Stocks Basic price history starts at approximately "
            f"{earliest_massive_date.isoformat()} for an evaluation date of "
            f"{plan.evaluated_on.isoformat()}; target_date={plan.target_date.isoformat()}"
        )
    if plan.alpha_vantage_requests > policies.alpha_vantage_requests_per_day:
        raise SourceLimitViolation(
            f"Alpha Vantage free daily request limit exceeded: "
            f"{plan.alpha_vantage_requests} > {policies.alpha_vantage_requests_per_day}"
        )
    if plan.alpha_vantage_symbol_filter is not None:
        raise SourceLimitViolation(
            "The project earnings-calendar strategy must use the all-symbols response "
            "instead of one request per ticker"
        )
    if (
        plan.collect_sec_financials
        and policies.sec_financial_normalization_required
        and not plan.normalize_sec_financials
    ):
        raise SourceLimitViolation(
            "SEC financial collection requires concept, unit, duration, and fiscal-period "
            "normalization before analytics use"
        )
    massive_minimum_minutes = (
        math.ceil(plan.massive_requests / policies.massive_requests_per_minute)
        if plan.massive_requests
        else 0
    )
    return {
        "target_date": plan.target_date.isoformat(),
        "massive": {
            "plan": policies.massive_plan,
            "requests": plan.massive_requests,
            "requests_per_minute": policies.massive_requests_per_minute,
            "minimum_minutes": massive_minimum_minutes,
            "price_timing": policies.massive_price_timing,
            "price_history_years": policies.massive_price_history_years,
            "dividend_history_scope": policies.massive_dividend_history_scope,
            "news_history_scope": policies.massive_news_history_scope,
        },
        "sec_edgar": {
            "json_api_enabled": policies.sec_edgar_json_api_enabled,
            "bulk_zip_enabled": policies.sec_edgar_bulk_zip_enabled,
            "financial_normalization_required": (policies.sec_financial_normalization_required),
        },
        "alpha_vantage": {
            "requests": plan.alpha_vantage_requests,
            "requests_per_day": policies.alpha_vantage_requests_per_day,
            "earnings_scope": policies.alpha_vantage_earnings_scope,
            "symbol_filter": None,
        },
    }
