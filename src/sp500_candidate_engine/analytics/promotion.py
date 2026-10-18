from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from numbers import Real
from pathlib import Path
from types import MappingProxyType

from sp500_candidate_engine.analytics.config import (
    AnalyticsConfigError,
    load_versioned_config,
)

MODEL_PURPOSES = frozenset({"SHORT_5D", "MEDIUM_20D"})
DEFAULT_WEEKLY_POLICY_VERSION = "weekly-v2-20d-performance-suspended"
WEEKLY_POLICY_FILES = {
    "weekly-v1": "weekly_retraining_v1.yaml",
    DEFAULT_WEEKLY_POLICY_VERSION: "weekly_retraining_v2.yaml",
}
PERFORMANCE_METRICS = frozenset({
    "rank_ic_mean", "fold_rank_ic_median", "net_top_10_return", "max_drawdown_top_10",
})


@dataclass(frozen=True)
class AbsoluteGate:
    minimum: float | None = None
    maximum: float | None = None


@dataclass(frozen=True)
class RelativeGate:
    minimum_delta: float


@dataclass(frozen=True)
class PurposePromotionPolicy:
    absolute: Mapping[str, AbsoluteGate]
    relative: Mapping[str, RelativeGate]


@dataclass(frozen=True)
class WeeklyRetrainingPolicy:
    version: str
    purposes: Mapping[str, PurposePromotionPolicy]
    performance_gates_enabled: bool = True
    suspension_reason: str | None = None


@dataclass(frozen=True)
class GateResult:
    passed: bool
    actual: float | None
    threshold: float | None
    incumbent: float | None = None
    reason: str | None = None
    enforced: bool = True


@dataclass(frozen=True)
class PromotionEvaluation:
    decision: str
    gate_results: Mapping[str, GateResult]

    @property
    def promoted(self) -> bool:
        return self.decision == "PROMOTE"


def _purpose(model_purpose: str) -> str:
    if model_purpose not in MODEL_PURPOSES:
        raise ValueError(f"Unsupported model purpose: {model_purpose}")
    return model_purpose


def _mapping(value: object, *, name: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise AnalyticsConfigError(f"{name} must be a mapping")
    return value


def _finite_config_number(value: object, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise AnalyticsConfigError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise AnalyticsConfigError(f"{name} must be finite")
    return result


def load_weekly_retraining_policy(path: Path) -> WeeklyRetrainingPolicy:
    config = load_versioned_config(path, required_keys=("promotion",))
    promotion = _mapping(config.payload["promotion"], name="promotion")
    purposes = _mapping(promotion.get("purposes"), name="promotion.purposes")
    if not purposes or not set(purposes) <= MODEL_PURPOSES:
        raise AnalyticsConfigError(
            "promotion.purposes must contain supported model purposes"
        )
    performance_enabled = promotion.get("performance_gates_enabled", True)
    if not isinstance(performance_enabled, bool):
        raise AnalyticsConfigError("promotion.performance_gates_enabled must be boolean")
    suspension_reason = promotion.get("suspension_reason")
    if suspension_reason is not None and not isinstance(suspension_reason, str):
        raise AnalyticsConfigError("promotion.suspension_reason must be text")
    if not performance_enabled and (
        suspension_reason is None or not suspension_reason.strip()
    ):
        raise AnalyticsConfigError("Suspended performance gates require a suspension_reason")

    parsed: dict[str, PurposePromotionPolicy] = {}
    for purpose_name, purpose_value in purposes.items():
        purpose = _purpose(purpose_name)
        purpose_mapping = _mapping(purpose_value, name=f"promotion.purposes.{purpose}")
        absolute_values = _mapping(
            purpose_mapping.get("absolute"), name=f"{purpose}.absolute"
        )
        relative_values = _mapping(
            purpose_mapping.get("relative"), name=f"{purpose}.relative"
        )
        if not absolute_values:
            raise AnalyticsConfigError(f"{purpose}.absolute must not be empty")
        absolute: dict[str, AbsoluteGate] = {}
        for metric, raw_gate in absolute_values.items():
            gate = _mapping(raw_gate, name=f"{purpose}.absolute.{metric}")
            unknown = set(gate) - {"minimum", "maximum"}
            if unknown or not gate:
                raise AnalyticsConfigError(
                    f"{purpose}.absolute.{metric} must define minimum and/or maximum"
                )
            minimum = (
                _finite_config_number(
                    gate["minimum"], name=f"{purpose}.absolute.{metric}.minimum"
                )
                if "minimum" in gate
                else None
            )
            maximum = (
                _finite_config_number(
                    gate["maximum"], name=f"{purpose}.absolute.{metric}.maximum"
                )
                if "maximum" in gate
                else None
            )
            if minimum is not None and maximum is not None and minimum > maximum:
                raise AnalyticsConfigError(
                    f"{purpose}.absolute.{metric} has an invalid range"
                )
            absolute[str(metric)] = AbsoluteGate(minimum=minimum, maximum=maximum)

        relative: dict[str, RelativeGate] = {}
        for metric, raw_gate in relative_values.items():
            gate = _mapping(raw_gate, name=f"{purpose}.relative.{metric}")
            if set(gate) != {"minimum_delta"}:
                raise AnalyticsConfigError(
                    f"{purpose}.relative.{metric} must define only minimum_delta"
                )
            relative[str(metric)] = RelativeGate(
                minimum_delta=_finite_config_number(
                    gate["minimum_delta"],
                    name=f"{purpose}.relative.{metric}.minimum_delta",
                )
            )
        parsed[purpose] = PurposePromotionPolicy(
            absolute=MappingProxyType(absolute),
            relative=MappingProxyType(relative),
        )
    return WeeklyRetrainingPolicy(
        version=config.version,
        purposes=MappingProxyType(parsed),
        performance_gates_enabled=performance_enabled,
        suspension_reason=suspension_reason,
    )


def weekly_retraining_policy_path(config_root: Path, policy_version: str) -> Path:
    filename = WEEKLY_POLICY_FILES.get(policy_version)
    if filename is None:
        raise AnalyticsConfigError(f"Unsupported weekly policy version: {policy_version}")
    return config_root / filename


def _metric(metrics: Mapping[str, object], name: str) -> float | None:
    value = metrics.get(name)
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    result = float(value)
    if not math.isfinite(result) or (name == "test_blocks" and not result.is_integer()):
        return None
    return result


def evaluate_promotion(
    *,
    policy: WeeklyRetrainingPolicy,
    model_purpose: str,
    challenger_metrics: Mapping[str, object],
    incumbent_metrics: Mapping[str, object] | None,
) -> PromotionEvaluation:
    purpose_policy = policy.purposes.get(_purpose(model_purpose))
    if purpose_policy is None:
        raise ValueError(f"Policy does not define model purpose: {model_purpose}")

    results: dict[str, GateResult] = {}
    for name, gate in purpose_policy.absolute.items():
        value = _metric(challenger_metrics, name)
        if value is None:
            results[f"absolute.{name}"] = GateResult(
                passed=False,
                actual=None,
                threshold=gate.minimum if gate.minimum is not None else gate.maximum,
                reason="missing_or_non_finite",
            )
            continue
        passed = (gate.minimum is None or value >= gate.minimum) and (
            gate.maximum is None or value <= gate.maximum
        )
        results[f"absolute.{name}"] = GateResult(
            passed=passed,
            actual=value,
            threshold=gate.minimum if gate.minimum is not None else gate.maximum,
            reason=None if passed else "threshold_not_met",
        )

    for name, gate in purpose_policy.relative.items():
        challenger = _metric(challenger_metrics, name)
        if challenger is None:
            results[f"relative.{name}"] = GateResult(
                passed=False,
                actual=None,
                threshold=gate.minimum_delta,
                reason="challenger_missing_or_non_finite",
            )
            continue
        if incumbent_metrics is None:
            results[f"relative.{name}"] = GateResult(
                passed=True,
                actual=challenger,
                threshold=gate.minimum_delta,
                reason="no_incumbent",
            )
            continue
        incumbent = _metric(incumbent_metrics, name)
        if incumbent is None:
            results[f"relative.{name}"] = GateResult(
                passed=False,
                actual=challenger,
                threshold=gate.minimum_delta,
                reason="incumbent_missing_or_non_finite",
            )
            continue
        delta = challenger - incumbent
        passed = delta >= gate.minimum_delta
        results[f"relative.{name}"] = GateResult(
            passed=passed,
            actual=delta,
            threshold=gate.minimum_delta,
            incumbent=incumbent,
            reason=None if passed else "relative_delta_not_met",
        )

    if not policy.performance_gates_enabled:
        results = {
            name: replace(gate, enforced=False)
            if name.partition(".")[2] in PERFORMANCE_METRICS
            and gate.reason in {None, "threshold_not_met", "relative_delta_not_met", "no_incumbent"}
            else gate
            for name, gate in results.items()
        }
    decision = (
        "PROMOTE" if results and all(item.passed or not item.enforced for item in results.values())
        else "REJECT"
    )
    return PromotionEvaluation(
        decision=decision,
        gate_results=MappingProxyType(results),
    )
