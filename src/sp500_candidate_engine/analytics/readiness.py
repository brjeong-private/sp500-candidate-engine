from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FeatureAvailability:
    p1_long_price_ready: bool
    p2_normalized_sec_ready: bool
    point_in_time_market_cap_ready: bool
    corporate_action_history_ready: bool
    historical_news_classified_coverage: float | None
    selected_feature_set_ready: bool = True
    minimum_news_coverage: float = 0.8


@dataclass(frozen=True)
class ExperimentReadiness:
    experiment_code: str
    status: str
    blocking_reasons: tuple[str, ...]


@dataclass(frozen=True)
class ExperimentSelection:
    experiment_code: str | None
    status: str
    reason: str


def assess_e2_e6_readiness(
    availability: FeatureAvailability,
) -> tuple[ExperimentReadiness, ...]:
    reasons: dict[str, list[str]] = {code: [] for code in ("E2", "E3", "E4", "E5", "E6")}
    if not availability.p1_long_price_ready:
        for code in ("E2", "E3", "E4"):
            reasons[code].append("P1_LONG_PRICE_UNAVAILABLE")
    if not availability.p2_normalized_sec_ready:
        for code in ("E3", "E4"):
            reasons[code].append("P2_NORMALIZED_SEC_UNAVAILABLE")
    if not availability.point_in_time_market_cap_ready:
        reasons["E4"].append("P3_POINT_IN_TIME_MARKET_CAP_UNAVAILABLE")
    if not availability.selected_feature_set_ready:
        for code in ("E5", "E6"):
            reasons[code].append("SELECTED_FEATURE_SET_UNAVAILABLE")
    if not availability.corporate_action_history_ready:
        for code in ("E5", "E6"):
            reasons[code].append("TOTAL_RETURN_ACTION_HISTORY_UNAVAILABLE")
    coverage = availability.historical_news_classified_coverage
    if coverage is None or coverage < availability.minimum_news_coverage:
        reasons["E6"].append("HISTORICAL_CLASSIFIED_NEWS_COVERAGE_UNAVAILABLE")
    return tuple(
        ExperimentReadiness(
            experiment_code=code,
            status="READY" if not blockers else "BLOCKED",
            blocking_reasons=tuple(blockers),
        )
        for code, blockers in reasons.items()
    )


def select_best_eligible_experiment(
    *,
    assessments: tuple[ExperimentReadiness, ...],
    ranked_experiments: tuple[str, ...],
) -> ExperimentSelection:
    """Select by precomputed validation rank without making optional E6 fatal."""
    by_code = {assessment.experiment_code: assessment for assessment in assessments}
    for experiment_code in ranked_experiments:
        assessment = by_code.get(experiment_code)
        if assessment is not None and assessment.status == "READY":
            return ExperimentSelection(
                experiment_code=experiment_code,
                status="SELECTED",
                reason=(
                    "BEST_ELIGIBLE"
                    if experiment_code == "E6"
                    else "BEST_ELIGIBLE_NON_LLM"
                ),
            )
    return ExperimentSelection(
        experiment_code=None,
        status="BLOCKED",
        reason="NO_ELIGIBLE_EXPERIMENT",
    )
