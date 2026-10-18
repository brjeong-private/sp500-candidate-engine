from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from pathlib import Path

from sp500_candidate_engine.analytics.config import VersionedConfig, load_versioned_config


@dataclass(frozen=True)
class EvidenceWindows:
    news_days: int
    earnings_events: int
    filings_days: int
    fact_quarters: int
    corporate_actions_days: int
    price_sessions: int


@dataclass(frozen=True)
class EvidenceLimits:
    news_items: int
    filings: int
    facts: int
    corporate_actions: int
    rationale_characters: int
    packet_characters: int
    total_input_tokens: int


@dataclass(frozen=True)
class ScreeningConfig:
    maximum_issuers: int
    control_issuers: int
    lookback_days: int
    earnings_window_days: int

    def __post_init__(self) -> None:
        if (
            any(type(value) is not int for value in (
                self.maximum_issuers, self.control_issuers,
                self.lookback_days, self.earnings_window_days,
            ))
            or self.maximum_issuers < 20 or not 0 <= self.control_issuers < self.maximum_issuers
            or self.lookback_days <= 0 or self.earnings_window_days <= 0
        ):
            raise ValueError("Invalid event screening configuration")


@dataclass(frozen=True)
class RateLimits:
    requests_per_minute: int
    tokens_per_minute: int
    output_token_reserve: int

    def __post_init__(self) -> None:
        if any(type(value) is not int or value <= 0 for value in (
            self.requests_per_minute, self.tokens_per_minute, self.output_token_reserve
        )) or self.output_token_reserve >= self.tokens_per_minute:
            raise ValueError("Invalid LLM rate limits")


@dataclass(frozen=True)
class ExternalEnrichmentConfig:
    provider: str
    max_documents: int
    max_response_bytes: int
    max_facts: int
    reserved_characters: int
    max_tool_calls: int
    on_admission_failure: str = "FAIL_RUN"

    def __post_init__(self) -> None:
        if self.on_admission_failure not in {"FAIL_RUN", "OMIT_EXTERNAL"}:
            raise ValueError("Invalid external admission failure policy")
        if self.provider not in {"AZURE_OPENAI_WEB_SEARCH", "AZURE_BING_GROUNDING_PERIOD"} or any(
            type(value) is not int or value <= 0 for value in (
                self.max_documents, self.max_response_bytes, self.max_facts,
                self.reserved_characters,
                self.max_tool_calls,
            )
        ) or self.max_documents > 2 or self.max_response_bytes > 8 * 1024 * 1024 \
                or self.max_facts > 20 or self.max_tool_calls > 3:
            raise ValueError("Invalid external enrichment configuration")


@dataclass(frozen=True)
class LlmPreselectionConfig:
    versioned: VersionedConfig
    requested_count: int
    first_stage_pool_size: int
    batch_size: int
    prompt_version: str
    evidence_schema_version: str
    windows: EvidenceWindows
    limits: EvidenceLimits
    max_attempts: int
    base_delay_seconds: float
    rubric: dict[str, int]
    screening: ScreeningConfig | None = None
    rate_limits: RateLimits | None = None
    max_delay_seconds: float = 60.0
    enrichment: ExternalEnrichmentConfig | None = None

    @property
    def policy_version(self) -> str:
        return f"{self.versioned.name}:{self.versioned.version}"

    @property
    def event_policy(self) -> bool:
        return self.screening is not None


def _positive_int(mapping: dict[str, object], key: str) -> int:
    value = mapping[key]
    if type(value) is not int or value <= 0:
        raise ValueError(f"{key} must be positive")
    return value


def _mapping(payload: dict[str, object], key: str) -> dict[str, object]:
    value = payload[key]
    if not isinstance(value, dict) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{key} must be a string-keyed mapping")
    return {str(item): entry for item, entry in value.items()}


def _number(value: object, name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")
    return float(value)


def load_llm_preselection_config(path: Path) -> LlmPreselectionConfig:
    versioned = load_versioned_config(
        path,
        required_keys=(
            "selection_type",
            "evidence_schema_version",
            "prompt_version",
            "requested_count",
            "first_stage_pool_size",
            "batch_size",
            "windows",
            "limits",
            "retries",
            "rubric",
        ),
    )
    payload = versioned.payload
    if payload["selection_type"] != "LLM_PRESELECTION":
        raise ValueError("selection_type must be LLM_PRESELECTION")
    windows = _mapping(payload, "windows")
    limits = _mapping(payload, "limits")
    retries = _mapping(payload, "retries")
    raw_rubric = _mapping(payload, "rubric")
    rubric = {key: _positive_int(raw_rubric, key) for key in raw_rubric}
    requested_count = _positive_int(payload, "requested_count")
    pool_size = _positive_int(payload, "first_stage_pool_size")
    screening = None
    if payload.get("evaluation_mode", "LEGACY_TWO_STAGE") == "EVENT_SCREENED":
        raw_screening = payload.get("screening")
        if not isinstance(raw_screening, dict):
            raise ValueError("Event policy requires screening settings")
        maximum = _positive_int(raw_screening, "maximum_issuers")
        controls = raw_screening.get("control_issuers")
        if type(controls) is not int or not 0 <= controls < maximum or maximum < 20:
            raise ValueError("Invalid screening quotas")
        screening = ScreeningConfig(
            maximum, controls,
            _positive_int(raw_screening, "lookback_days"),
            _positive_int(raw_screening, "earnings_window_days"),
        )
        if windows.get("price_sessions") != 0:
            raise ValueError("Event policy must exclude price context")
        if rubric != {"earnings": 25, "business": 25, "event": 20,
                      "financial": 15, "industry": 15}:
            raise ValueError("Event rubric must match the versioned five-criterion contract")
    elif payload.get("evaluation_mode", "LEGACY_TWO_STAGE") != "LEGACY_TWO_STAGE":
        raise ValueError("Unknown LLM evaluation mode")
    if requested_count != 20:
        raise ValueError("LLM preselection requested_count must be 20")
    if pool_size < requested_count:
        raise ValueError("first_stage_pool_size must cover requested_count")
    if sum(rubric.values()) != 100 or any(value <= 0 for value in rubric.values()):
        raise ValueError("rubric weights must be positive and sum to 100")
    delay = _number(retries["base_delay_seconds"], "base_delay_seconds")
    max_delay = _number(retries.get("max_delay_seconds", 60), "max_delay_seconds")
    if not isfinite(delay) or delay < 0:
        raise ValueError("base_delay_seconds must be finite and nonnegative")
    if not isfinite(max_delay) or max_delay <= 0 or delay > max_delay:
        raise ValueError("Retry delays must fit the finite delay budget")
    rate_limits = None
    enrichment = None
    if "external_enrichment" in payload:
        external = _mapping(payload, "external_enrichment")
        enrichment = ExternalEnrichmentConfig(
            str(external["provider"]), _positive_int(external, "max_documents"),
            _positive_int(external, "max_response_bytes"),
            _positive_int(external, "max_facts"),
            _positive_int(external, "reserved_characters"),
            _positive_int(external, "max_tool_calls"),
            str(external.get("on_admission_failure", "FAIL_RUN")),
        )
        if screening is None or str(payload["evidence_schema_version"]) != "4" \
                or enrichment.reserved_characters >= _positive_int(limits, "packet_characters"):
            raise ValueError("External enrichment requires event schema 3 and a bounded reserve")
    if "rate_limits" in payload:
        raw_limits = payload["rate_limits"]
        if not isinstance(raw_limits, dict):
            raise ValueError("rate_limits must be a mapping")
        rate_limits = RateLimits(
            _positive_int(raw_limits, "requests_per_minute"),
            _positive_int(raw_limits, "tokens_per_minute"),
            _positive_int(raw_limits, "output_token_reserve"),
        )
        if rate_limits.output_token_reserve >= rate_limits.tokens_per_minute:
            raise ValueError("Output token reserve must fit within TPM budget")
    return LlmPreselectionConfig(
        versioned=versioned,
        requested_count=requested_count,
        first_stage_pool_size=pool_size,
        batch_size=_positive_int(payload, "batch_size"),
        prompt_version=str(payload["prompt_version"]),
        evidence_schema_version=str(payload["evidence_schema_version"]),
        windows=EvidenceWindows(
            news_days=_positive_int(windows, "news_days"),
            earnings_events=_positive_int(windows, "earnings_events"),
            filings_days=_positive_int(windows, "filings_days"),
            fact_quarters=_positive_int(windows, "fact_quarters"),
            corporate_actions_days=_positive_int(windows, "corporate_actions_days"),
            price_sessions=0 if screening else _positive_int(windows, "price_sessions"),
        ),
        limits=EvidenceLimits(
            news_items=_positive_int(limits, "news_items"),
            filings=_positive_int(limits, "filings"),
            facts=_positive_int(limits, "facts"),
            corporate_actions=_positive_int(limits, "corporate_actions"),
            rationale_characters=_positive_int(limits, "rationale_characters"),
            packet_characters=_positive_int(limits, "packet_characters"),
            total_input_tokens=_positive_int(limits, "total_input_tokens"),
        ),
        max_attempts=_positive_int(retries, "max_attempts"),
        base_delay_seconds=delay,
        rubric=rubric,
        screening=screening,
        rate_limits=rate_limits,
        max_delay_seconds=max_delay,
        enrichment=enrichment,
    )
