from __future__ import annotations

from dataclasses import dataclass
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

    @property
    def policy_version(self) -> str:
        return f"{self.versioned.name}:{self.versioned.version}"


def _positive_int(mapping: dict[str, object], key: str) -> int:
    value = int(mapping[key])
    if value <= 0:
        raise ValueError(f"{key} must be positive")
    return value


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
    windows = dict(payload["windows"])  # type: ignore[arg-type]
    limits = dict(payload["limits"])  # type: ignore[arg-type]
    retries = dict(payload["retries"])  # type: ignore[arg-type]
    rubric = {str(key): int(value) for key, value in dict(payload["rubric"]).items()}  # type: ignore[arg-type]
    requested_count = _positive_int(payload, "requested_count")
    pool_size = _positive_int(payload, "first_stage_pool_size")
    if requested_count != 20:
        raise ValueError("LLM preselection requested_count must be 20")
    if pool_size < requested_count:
        raise ValueError("first_stage_pool_size must cover requested_count")
    if sum(rubric.values()) != 100 or any(value <= 0 for value in rubric.values()):
        raise ValueError("rubric weights must be positive and sum to 100")
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
            price_sessions=_positive_int(windows, "price_sessions"),
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
        base_delay_seconds=float(retries["base_delay_seconds"]),
        rubric=rubric,
    )
