from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from sp500_candidate_engine.source_harness import SourcePolicies


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Required environment variable is missing: {name}")
    return value


def _optional(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return value or None


def _boolean(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    raise ValueError(f"{name} must be true or false")


@dataclass(frozen=True)
class Settings:
    azure_subscription_id: str
    azure_tenant_id: str
    azure_credential_mode: str
    pg_host: str
    pg_port: int
    pg_database: str
    pg_user: str
    pg_sslmode: str
    pg_connect_timeout: int
    max_concurrency: int
    http_timeout_seconds: float
    max_attempts: int
    min_success_ratio: float
    http_user_agent: str
    raw_data_dir: Path
    log_dir: Path
    market_data_provider: str
    corporate_action_provider: str
    news_data_provider: str
    identifier_data_provider: str
    earnings_calendar_provider: str
    fundamentals_data_provider: str
    massive_api_key: str | None
    massive_base_url: str
    massive_plan: str
    massive_requests_per_minute: int
    massive_price_timing: str
    massive_price_history_years: int
    massive_dividend_history_scope: str
    massive_news_history_scope: str
    alpha_vantage_api_key: str | None
    alpha_vantage_base_url: str
    alpha_vantage_requests_per_day: int
    alpha_vantage_earnings_scope: str
    sec_edgar_json_api_enabled: bool
    sec_edgar_bulk_zip_enabled: bool
    sec_financial_normalization_required: bool

    @classmethod
    def from_env(cls, env_file: str | Path = ".env") -> Settings:
        load_dotenv(env_file)
        settings = cls(
            azure_subscription_id=_required("AZURE_SUBSCRIPTION_ID"),
            azure_tenant_id=_required("AZURE_TENANT_ID"),
            azure_credential_mode=os.getenv("AZURE_CREDENTIAL_MODE", "default"),
            pg_host=_required("PGHOST"),
            pg_port=int(os.getenv("PGPORT", "5432")),
            pg_database=_required("PGDATABASE"),
            pg_user=_required("PGUSER"),
            pg_sslmode=os.getenv("PGSSLMODE", "require"),
            pg_connect_timeout=int(os.getenv("PGCONNECT_TIMEOUT", "30")),
            max_concurrency=int(os.getenv("COLLECTOR_MAX_CONCURRENCY", "6")),
            http_timeout_seconds=float(os.getenv("COLLECTOR_HTTP_TIMEOUT_SECONDS", "30")),
            max_attempts=int(os.getenv("COLLECTOR_MAX_ATTEMPTS", "4")),
            min_success_ratio=float(os.getenv("COLLECTOR_MIN_SUCCESS_RATIO", "0.95")),
            http_user_agent=os.getenv(
                "HTTP_USER_AGENT", "sp500-candidate-engine/0.1 data-research"
            ),
            raw_data_dir=Path(os.getenv("RAW_DATA_DIR", "data/raw")),
            log_dir=Path(os.getenv("LOG_DIR", "logs")),
            market_data_provider=os.getenv("MARKET_DATA_PROVIDER", "massive"),
            corporate_action_provider=os.getenv("CORPORATE_ACTION_PROVIDER", "massive"),
            news_data_provider=os.getenv("NEWS_DATA_PROVIDER", "massive"),
            identifier_data_provider=os.getenv("IDENTIFIER_DATA_PROVIDER", "sec_edgar"),
            earnings_calendar_provider=os.getenv("EARNINGS_CALENDAR_PROVIDER", "alpha_vantage"),
            fundamentals_data_provider=os.getenv("FUNDAMENTALS_DATA_PROVIDER", "sec_edgar"),
            massive_api_key=_optional("MASSIVE_API_KEY"),
            massive_base_url=os.getenv("MASSIVE_BASE_URL", "https://api.massive.com"),
            massive_plan=os.getenv("MASSIVE_PLAN", "stocks_basic"),
            massive_requests_per_minute=int(os.getenv("MASSIVE_REQUESTS_PER_MINUTE", "5")),
            massive_price_timing=os.getenv("MASSIVE_PRICE_TIMING", "end_of_day"),
            massive_price_history_years=int(os.getenv("MASSIVE_PRICE_HISTORY_YEARS", "2")),
            massive_dividend_history_scope=os.getenv(
                "MASSIVE_DIVIDEND_HISTORY_SCOPE", "free_plan_limited"
            ),
            massive_news_history_scope=os.getenv("MASSIVE_NEWS_HISTORY_SCOPE", "free_plan_limited"),
            alpha_vantage_api_key=_optional("ALPHA_VANTAGE_API_KEY"),
            alpha_vantage_base_url=os.getenv(
                "ALPHA_VANTAGE_BASE_URL", "https://www.alphavantage.co/query"
            ),
            alpha_vantage_requests_per_day=int(os.getenv("ALPHA_VANTAGE_REQUESTS_PER_DAY", "25")),
            alpha_vantage_earnings_scope=os.getenv("ALPHA_VANTAGE_EARNINGS_SCOPE", "all_symbols"),
            sec_edgar_json_api_enabled=_boolean("SEC_EDGAR_JSON_API_ENABLED", True),
            sec_edgar_bulk_zip_enabled=_boolean("SEC_EDGAR_BULK_ZIP_ENABLED", True),
            sec_financial_normalization_required=_boolean(
                "SEC_FINANCIAL_NORMALIZATION_REQUIRED", True
            ),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.azure_credential_mode not in {"default", "azure_cli"}:
            raise ValueError("AZURE_CREDENTIAL_MODE must be 'default' or 'azure_cli'")
        if not 1 <= self.max_concurrency <= 32:
            raise ValueError("COLLECTOR_MAX_CONCURRENCY must be between 1 and 32")
        if not 0 < self.min_success_ratio <= 1:
            raise ValueError("COLLECTOR_MIN_SUCCESS_RATIO must be in (0, 1]")
        if self.pg_sslmode not in {"require", "verify-ca", "verify-full"}:
            raise ValueError("PGSSLMODE must require TLS")
        expected_providers = {
            "MARKET_DATA_PROVIDER": (self.market_data_provider, "massive"),
            "CORPORATE_ACTION_PROVIDER": (self.corporate_action_provider, "massive"),
            "NEWS_DATA_PROVIDER": (self.news_data_provider, "massive"),
            "IDENTIFIER_DATA_PROVIDER": (self.identifier_data_provider, "sec_edgar"),
            "EARNINGS_CALENDAR_PROVIDER": (
                self.earnings_calendar_provider,
                "alpha_vantage",
            ),
            "FUNDAMENTALS_DATA_PROVIDER": (
                self.fundamentals_data_provider,
                "sec_edgar",
            ),
        }
        for name, (actual, expected) in expected_providers.items():
            if actual != expected:
                raise ValueError(f"{name} must be {expected!r}, got {actual!r}")
        expected_limits = {
            "MASSIVE_PLAN": (self.massive_plan, "stocks_basic"),
            "MASSIVE_REQUESTS_PER_MINUTE": (
                self.massive_requests_per_minute,
                5,
            ),
            "MASSIVE_PRICE_TIMING": (self.massive_price_timing, "end_of_day"),
            "MASSIVE_PRICE_HISTORY_YEARS": (
                self.massive_price_history_years,
                2,
            ),
            "MASSIVE_DIVIDEND_HISTORY_SCOPE": (
                self.massive_dividend_history_scope,
                "free_plan_limited",
            ),
            "MASSIVE_NEWS_HISTORY_SCOPE": (
                self.massive_news_history_scope,
                "free_plan_limited",
            ),
            "ALPHA_VANTAGE_REQUESTS_PER_DAY": (
                self.alpha_vantage_requests_per_day,
                25,
            ),
            "ALPHA_VANTAGE_EARNINGS_SCOPE": (
                self.alpha_vantage_earnings_scope,
                "all_symbols",
            ),
            "SEC_EDGAR_JSON_API_ENABLED": (
                self.sec_edgar_json_api_enabled,
                True,
            ),
            "SEC_EDGAR_BULK_ZIP_ENABLED": (
                self.sec_edgar_bulk_zip_enabled,
                True,
            ),
            "SEC_FINANCIAL_NORMALIZATION_REQUIRED": (
                self.sec_financial_normalization_required,
                True,
            ),
        }
        for name, (actual, expected) in expected_limits.items():
            if actual != expected:
                raise ValueError(f"{name} must be {expected!r}, got {actual!r}")

    def source_policies(self) -> SourcePolicies:
        return SourcePolicies(
            massive_plan=self.massive_plan,
            massive_requests_per_minute=self.massive_requests_per_minute,
            massive_price_timing=self.massive_price_timing,
            massive_price_history_years=self.massive_price_history_years,
            massive_dividend_history_scope=self.massive_dividend_history_scope,
            massive_news_history_scope=self.massive_news_history_scope,
            sec_edgar_json_api_enabled=self.sec_edgar_json_api_enabled,
            sec_edgar_bulk_zip_enabled=self.sec_edgar_bulk_zip_enabled,
            sec_financial_normalization_required=(self.sec_financial_normalization_required),
            alpha_vantage_requests_per_day=self.alpha_vantage_requests_per_day,
            alpha_vantage_earnings_scope=self.alpha_vantage_earnings_scope,
        )

    def provider_status(self) -> dict[str, dict[str, object]]:
        return {
            "massive": {
                "configured": self.massive_api_key is not None,
                "base_url": self.massive_base_url,
                "uses": ["market_data", "corporate_actions", "news"],
                "plan": self.massive_plan,
            },
            "alpha_vantage": {
                "configured": self.alpha_vantage_api_key is not None,
                "base_url": self.alpha_vantage_base_url,
                "uses": ["earnings_calendar"],
                "earnings_scope": self.alpha_vantage_earnings_scope,
            },
            "sec_edgar": {
                "configured": bool(self.http_user_agent),
                "base_url": "https://data.sec.gov",
                "uses": ["identifiers", "filings", "fundamentals"],
            },
        }

    def collection_config_hash(self) -> str:
        payload = {
            "collector_version": "0.1.0",
            "universe_provider": "wikipedia_revision",
            "market_provider": "yahoo_chart",
            "max_concurrency": self.max_concurrency,
            "min_success_ratio": self.min_success_ratio,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    def production_config_hash(self) -> str:
        payload = {
            "collector_version": "0.1.0",
            "universe_provider": "wikipedia_revision",
            "market_provider": self.market_data_provider,
            "corporate_action_provider": self.corporate_action_provider,
            "news_provider": self.news_data_provider,
            "identifier_provider": self.identifier_data_provider,
            "earnings_provider": self.earnings_calendar_provider,
            "fundamentals_provider": self.fundamentals_data_provider,
            "source_policies": self.source_policies().as_dict(),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()
