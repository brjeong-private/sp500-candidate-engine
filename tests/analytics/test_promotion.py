from __future__ import annotations

from pathlib import Path

import pytest

from sp500_candidate_engine.analytics.promotion import (
    evaluate_promotion,
    load_weekly_retraining_policy,
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
