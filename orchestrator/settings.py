"""오케스트레이터 설정을 검증해 외부 계약을 fail-closed로 만든다."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlsplit


class ConfigurationError(RuntimeError):
    """필수 설정이 없거나 안전하지 않을 때 발생한다."""


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigurationError(f"{name} is required")
    return value


def https_base_url(name: str) -> str:
    value = required(name).rstrip("/")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ConfigurationError(
            f"{name} must be an HTTPS URL without credentials, query, or fragment"
        )
    return value


def optional_https_base_url(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    if not value:
        return None
    parsed = urlsplit(value.rstrip("/"))
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ConfigurationError(
            f"{name} must be an HTTPS URL without credentials, query, or fragment"
        )
    return value.rstrip("/")


def azure_resource_id(name: str) -> str:
    value = required(name)
    if (
        not value.startswith("/subscriptions/")
        or ".." in value
        or "?" in value
        or "#" in value
        or any(character.isspace() for character in value)
    ):
        raise ConfigurationError(f"{name} must be an Azure resource ID")
    return value


def resource_access(name: str) -> str:
    value = required(name).capitalize()
    if value not in {"Enabled", "Disabled"}:
        raise ConfigurationError(f"{name} must be Enabled or Disabled")
    return value


def positive_int(name: str) -> int:
    try:
        value = int(required(name))
    except ValueError as error:
        raise ConfigurationError(f"{name} must be a positive integer") from error
    if value <= 0:
        raise ConfigurationError(f"{name} must be a positive integer")
    return value


def network_action(name: str) -> str:
    value = required(name).capitalize()
    if value not in {"Allow", "Deny"}:
        raise ConfigurationError(f"{name} must be Allow or Deny")
    return value


def boolean_flag(name: str, default: bool) -> bool:
    value = os.environ.get(name, str(default)).strip().casefold()
    if value not in {"true", "false"}:
        raise ConfigurationError(f"{name} must be true or false")
    return value == "true"


@dataclass(frozen=True)
class Settings:
    candidate_base_url: str
    candidate_api_key: str
    candidate_resource_id: str
    candidate_postgres_resource_id: str
    candidate_postgres_public_network_access: str
    portal_base_url: str
    portal_api_key: str
    portal_resource_id: str
    portal_mysql_resource_id: str
    portal_mysql_public_network_access: str
    tradingagents_base_url: str | None
    tradingagents_resource_id: str
    tradingagents_min_replicas: int
    orchestrator_storage_resource_id: str
    orchestrator_storage_container_name: str
    orchestrator_storage_public_network_access: str
    orchestrator_storage_network_default_action: str
    acs_endpoint: str
    email_sender: str
    email_recipients: tuple[str, ...]
    exchange_mic: str
    email_enabled: bool = True

    @classmethod
    def from_env(cls) -> Settings:
        recipients = tuple(
            item.strip()
            for item in required("ORCHESTRATOR_EMAIL_RECIPIENTS").split(",")
            if item.strip()
        )
        if not recipients:
            raise ConfigurationError("ORCHESTRATOR_EMAIL_RECIPIENTS is empty")
        return cls(
            candidate_base_url=https_base_url("CANDIDATE_API_URL"),
            candidate_api_key=required("CANDIDATE_API_KEY"),
            candidate_resource_id=azure_resource_id("CANDIDATE_RESOURCE_ID"),
            candidate_postgres_resource_id=azure_resource_id("CANDIDATE_POSTGRES_RESOURCE_ID"),
            candidate_postgres_public_network_access=resource_access(
                "CANDIDATE_POSTGRES_PUBLIC_NETWORK_ACCESS"
            ),
            portal_base_url=https_base_url("PORTAL_API_URL"),
            portal_api_key=required("PORTAL_AUTOMATION_API_KEY"),
            portal_resource_id=azure_resource_id("PORTAL_RESOURCE_ID"),
            portal_mysql_resource_id=azure_resource_id("PORTAL_MYSQL_RESOURCE_ID"),
            portal_mysql_public_network_access=resource_access(
                "PORTAL_MYSQL_PUBLIC_NETWORK_ACCESS"
            ),
            tradingagents_base_url=optional_https_base_url("TRADINGAGENTS_API_URL"),
            tradingagents_resource_id=azure_resource_id("TRADINGAGENTS_RESOURCE_ID"),
            tradingagents_min_replicas=positive_int("TRADINGAGENTS_MIN_REPLICAS"),
            orchestrator_storage_resource_id=azure_resource_id("ORCHESTRATOR_STORAGE_RESOURCE_ID"),
            orchestrator_storage_container_name=required("ORCHESTRATOR_STORAGE_CONTAINER_NAME"),
            orchestrator_storage_public_network_access=resource_access(
                "ORCHESTRATOR_STORAGE_PUBLIC_NETWORK_ACCESS"
            ),
            orchestrator_storage_network_default_action=network_action(
                "ORCHESTRATOR_STORAGE_NETWORK_DEFAULT_ACTION"
            ),
            acs_endpoint=https_base_url("ACS_EMAIL_ENDPOINT"),
            email_sender=required("ORCHESTRATOR_EMAIL_SENDER"),
            email_recipients=recipients,
            exchange_mic=os.environ.get("ORCHESTRATOR_EXCHANGE_MIC", "XNYS").strip().upper(),
            email_enabled=boolean_flag("ORCHESTRATOR_EMAIL_ENABLED", True),
        )
