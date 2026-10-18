from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from sp500_candidate_engine.analytics.promotion import (
    DEFAULT_WEEKLY_POLICY_VERSION,
    PERFORMANCE_METRICS,
    AbsoluteGate,
    evaluate_promotion,
    load_weekly_retraining_policy,
    weekly_retraining_policy_path,
)

ROOT = Path(__file__).parents[2]


def _policy():
    return load_weekly_retraining_policy(
        ROOT / "config" / "analytics" / "weekly_retraining_v1.yaml"
    )


def _passing_metrics() -> dict[str, float]:
    return {
        "coverage": 0.95,
        "test_blocks": 4,
        "rank_ic_mean": 0.04,
        "fold_rank_ic_median": 0.03,
        "net_top_10_return": 0.08,
        "max_drawdown_top_10": -0.10,
    }


@pytest.mark.parametrize("purpose", ["SHORT_5D", "MEDIUM_20D"])
def test_absolute_and_incumbent_relative_gates_pass(purpose):
    incumbent = _passing_metrics()
    challenger = {name: value + 0.01 for name, value in incumbent.items()}
    challenger["coverage"] = incumbent["coverage"]
    challenger["test_blocks"] = incumbent["test_blocks"]

    result = evaluate_promotion(
        policy=_policy(),
        model_purpose=purpose,
        challenger_metrics=challenger,
        incumbent_metrics=incumbent,
    )

    assert result.decision == "PROMOTE"
    assert result.promoted
    assert all(gate.passed for gate in result.gate_results.values())


@pytest.mark.parametrize("invalid", [None, float("nan"), float("inf"), -float("inf")])
def test_metrics_fail_closed(invalid):
    metrics = _passing_metrics()
    metrics["rank_ic_mean"] = invalid

    result = evaluate_promotion(
        policy=_policy(),
        model_purpose="SHORT_5D",
        challenger_metrics=metrics,
        incumbent_metrics=_passing_metrics(),
    )

    assert result.decision == "REJECT"
    assert result.gate_results["absolute.rank_ic_mean"].reason == "missing_or_non_finite"


def test_relative_regression_rejects_and_bootstrap_needs_only_absolute_gates():
    challenger = _passing_metrics()
    incumbent = _passing_metrics()
    challenger["net_top_10_return"] = incumbent["net_top_10_return"] - 0.01

    rejected = evaluate_promotion(
        policy=_policy(),
        model_purpose="SHORT_5D",
        challenger_metrics=challenger,
        incumbent_metrics=incumbent,
    )
    bootstrap = evaluate_promotion(
        policy=_policy(),
        model_purpose="SHORT_5D",
        challenger_metrics=_passing_metrics(),
        incumbent_metrics=None,
    )

    assert rejected.decision == "REJECT"
    assert not rejected.gate_results["relative.net_top_10_return"].passed
    assert bootstrap.decision == "PROMOTE"


def test_rejects_cross_purpose_or_unknown_purpose():
    with pytest.raises(ValueError, match="Unsupported model purpose"):
        evaluate_promotion(
            policy=_policy(),
            model_purpose="OTHER",
            challenger_metrics=_passing_metrics(),
            incumbent_metrics=None,
        )


def _suspended_policy():
    return load_weekly_retraining_policy(weekly_retraining_policy_path(
        ROOT / "config" / "analytics", DEFAULT_WEEKLY_POLICY_VERSION,
    ))


def test_suspended_performance_thresholds_remain_failed_in_audit_but_do_not_block():
    metrics = {
        **_passing_metrics(), "rank_ic_mean": -0.02, "fold_rank_ic_median": -0.01,
        "net_top_10_return": -0.1, "max_drawdown_top_10": -0.5,
    }
    policy = _suspended_policy()
    result = evaluate_promotion(
        policy=policy, model_purpose="MEDIUM_20D",
        challenger_metrics=metrics, incumbent_metrics=_passing_metrics(),
    )
    assert set(policy.purposes) == {"MEDIUM_20D"}
    assert result.decision == "PROMOTE"
    assert policy.suspension_reason
    for name, gate in result.gate_results.items():
        if name.partition(".")[2] in PERFORMANCE_METRICS:
            assert not gate.passed
            assert not gate.enforced
            assert gate.reason in {"threshold_not_met", "relative_delta_not_met"}
        else:
            assert gate.passed and gate.enforced


@pytest.mark.parametrize(("name", "value"), [
    ("coverage", 0.79), ("test_blocks", 2),
    ("test_blocks", 3.5), ("rank_ic_mean", None),
    ("fold_rank_ic_median", float("nan")),
    ("net_top_10_return", float("inf")), ("max_drawdown_top_10", True),
])
def test_suspension_preserves_input_quality_and_finite_metric_requirements(name, value):
    result = evaluate_promotion(
        policy=_suspended_policy(), model_purpose="MEDIUM_20D",
        challenger_metrics={**_passing_metrics(), name: value}, incumbent_metrics=None,
    )
    assert result.decision == "REJECT"
    assert not result.gate_results[f"absolute.{name}"].passed
    assert result.gate_results[f"absolute.{name}"].enforced


def test_suspension_does_not_mask_invalid_incumbent_metrics_or_enable_short():
    result = evaluate_promotion(
        policy=_suspended_policy(), model_purpose="MEDIUM_20D",
        challenger_metrics=_passing_metrics(),
        incumbent_metrics={**_passing_metrics(), "rank_ic_mean": None},
    )
    assert result.decision == "REJECT"
    assert result.gate_results["relative.rank_ic_mean"].enforced
    with pytest.raises(ValueError, match="does not define"):
        evaluate_promotion(
            policy=_suspended_policy(), model_purpose="SHORT_5D",
            challenger_metrics=_passing_metrics(), incumbent_metrics=None,
        )


def test_policy_version_resolution_preserves_v1_and_rejects_unknown_versions():
    from sp500_candidate_engine.analytics.config import AnalyticsConfigError

    legacy = load_weekly_retraining_policy(weekly_retraining_policy_path(
        ROOT / "config" / "analytics", "weekly-v1",
    ))
    assert legacy.performance_gates_enabled
    assert set(legacy.purposes) == {"SHORT_5D", "MEDIUM_20D"}
    with pytest.raises(AnalyticsConfigError, match="Unsupported weekly policy"):
        weekly_retraining_policy_path(ROOT / "config" / "analytics", "weekly-unknown")


@pytest.mark.parametrize("change", [
    {"performance_gates_enabled": "false"},
    {"performance_gates_enabled": False, "suspension_reason": None},
    {"performance_gates_enabled": False, "suspension_reason": "  "},
    {"performance_gates_enabled": True, "suspension_reason": 42},
])
def test_invalid_suspension_configuration_fails_closed(tmp_path, change):
    from sp500_candidate_engine.analytics.config import AnalyticsConfigError

    payload = yaml.safe_load(
        (ROOT / "config" / "analytics" / "weekly_retraining_v2.yaml").read_text(
            encoding="utf-8"
        )
    )
    payload["promotion"].update(change)
    path = tmp_path / "policy.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    with pytest.raises(AnalyticsConfigError):
        load_weekly_retraining_policy(path)


def test_suspension_does_not_bypass_unlisted_gates():
    policy = _suspended_policy()
    purpose = policy.purposes["MEDIUM_20D"]
    policy = replace(policy, purposes={"MEDIUM_20D": replace(
        purpose, absolute={**purpose.absolute, "additional_safety_metric": AbsoluteGate(minimum=1)},
    )})
    result = evaluate_promotion(
        policy=policy, model_purpose="MEDIUM_20D",
        challenger_metrics={**_passing_metrics(), "additional_safety_metric": 0},
        incumbent_metrics=None,
    )
    assert result.decision == "REJECT"
    assert result.gate_results["absolute.additional_safety_metric"].enforced
