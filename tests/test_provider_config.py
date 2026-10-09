from dataclasses import replace
from pathlib import Path

from sp500_candidate_engine.config import Settings


def _settings() -> Settings:
    return Settings(
        azure_subscription_id="subscription",
        azure_tenant_id="tenant",
        azure_credential_mode="default",
        pg_host="example.postgres.database.azure.com",
        pg_port=5432,
        pg_database="candidate_engine",
        pg_user="user@example.com",
        pg_sslmode="require",
        pg_connect_timeout=30,
        max_concurrency=6,
        http_timeout_seconds=30,
        max_attempts=4,
        min_success_ratio=0.95,
        http_user_agent="candidate-engine contact@example.com",
        raw_data_dir=Path("data/raw"),
        log_dir=Path("logs"),
        market_data_provider="massive",
        corporate_action_provider="massive",
        news_data_provider="massive",
        identifier_data_provider="sec_edgar",
        earnings_calendar_provider="alpha_vantage",
        fundamentals_data_provider="sec_edgar",
        massive_api_key=None,
        massive_base_url="https://api.massive.com",
        massive_plan="stocks_basic",
        massive_requests_per_minute=5,
        massive_price_timing="end_of_day",
        massive_price_history_years=2,
        massive_dividend_history_scope="free_plan_limited",
        massive_news_history_scope="free_plan_limited",
        alpha_vantage_api_key=None,
        alpha_vantage_base_url="https://www.alphavantage.co/query",
        alpha_vantage_requests_per_day=25,
        alpha_vantage_earnings_scope="all_symbols",
        sec_edgar_json_api_enabled=True,
        sec_edgar_bulk_zip_enabled=True,
        sec_financial_normalization_required=True,
    )


def test_provider_status_does_not_expose_keys() -> None:
    settings = replace(
        _settings(),
        massive_api_key="secret-massive",
        alpha_vantage_api_key="secret-alpha",
    )
    status = settings.provider_status()
    assert all(provider["configured"] for provider in status.values())
    assert "secret" not in repr(status)


def test_expected_provider_selection_is_valid() -> None:
    settings = _settings()
    settings.validate()
