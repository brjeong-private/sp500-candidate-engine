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
    if not value.startswith("/subscriptions/") or ".." in value or "?" in value:
        raise ConfigurationError(f"{name} must be an Azure resource ID")
    return value


@dataclass(frozen=True)
class Settings:
    candidate_base_url: str
    candidate_api_key: str
    candidate_resource_id: str
    portal_base_url: str
    portal_api_key: str
    portal_resource_id: str
    tradingagents_base_url: str | None
    acs_endpoint: str
    email_sender: str
    email_recipients: tuple[str, ...]
    exchange_mic: str
    model_purpose: str

    @classmethod
    def from_env(cls) -> Settings:
        recipients = tuple(
            item.strip()
            for item in required("ORCHESTRATOR_EMAIL_RECIPIENTS").split(",")
            if item.strip()
        )
        if not recipients:
            raise ConfigurationError("ORCHESTRATOR_EMAIL_RECIPIENTS is empty")
        model_purpose = os.environ.get("ORCHESTRATOR_CANDIDATE_MODEL_PURPOSE", "MEDIUM_20D").strip()
        if model_purpose not in {"MEDIUM_20D", "SHORT_5D"}:
            raise ConfigurationError("invalid ORCHESTRATOR_CANDIDATE_MODEL_PURPOSE")
        return cls(
            candidate_base_url=https_base_url("CANDIDATE_API_URL"),
            candidate_api_key=required("CANDIDATE_API_KEY"),
            candidate_resource_id=azure_resource_id("CANDIDATE_RESOURCE_ID"),
            portal_base_url=https_base_url("PORTAL_API_URL"),
            portal_api_key=required("PORTAL_AUTOMATION_API_KEY"),
            portal_resource_id=azure_resource_id("PORTAL_RESOURCE_ID"),
            tradingagents_base_url=optional_https_base_url("TRADINGAGENTS_API_URL"),
            acs_endpoint=https_base_url("ACS_EMAIL_ENDPOINT"),
            email_sender=required("ORCHESTRATOR_EMAIL_SENDER"),
            email_recipients=recipients,
            exchange_mic=os.environ.get("ORCHESTRATOR_EXCHANGE_MIC", "XNYS").strip().upper(),
            model_purpose=model_purpose,
        )
