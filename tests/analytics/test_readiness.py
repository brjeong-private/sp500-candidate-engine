from sp500_candidate_engine.analytics.readiness import (
    FeatureAvailability,
    assess_e2_e6_readiness,
    select_best_eligible_experiment,
)


def test_p3_and_e6_fail_closed_when_required_history_is_absent() -> None:
    results = {
        result.experiment_code: result
        for result in assess_e2_e6_readiness(
            FeatureAvailability(
                p1_long_price_ready=True,
                p2_normalized_sec_ready=True,
                point_in_time_market_cap_ready=False,
                corporate_action_history_ready=True,
                historical_news_classified_coverage=None,
            )
        )
    }

    assert results["E2"].status == "READY"
    assert results["E3"].status == "READY"
    assert results["E4"].status == "BLOCKED"
    assert "P3_POINT_IN_TIME_MARKET_CAP_UNAVAILABLE" in results["E4"].blocking_reasons
    assert results["E5"].status == "READY"
    assert results["E6"].status == "BLOCKED"
    assert (
        "HISTORICAL_CLASSIFIED_NEWS_COVERAGE_UNAVAILABLE"
        in results["E6"].blocking_reasons
    )


def test_e6_requires_configured_historical_classification_coverage() -> None:
    result = assess_e2_e6_readiness(
        FeatureAvailability(
            p1_long_price_ready=True,
            p2_normalized_sec_ready=True,
            point_in_time_market_cap_ready=True,
            corporate_action_history_ready=True,
            historical_news_classified_coverage=0.79,
            minimum_news_coverage=0.8,
        )
    )[-1]

    assert result.experiment_code == "E6"
    assert result.status == "BLOCKED"


def test_blocked_e6_selects_best_eligible_non_llm_experiment() -> None:
    assessments = assess_e2_e6_readiness(
        FeatureAvailability(
            p1_long_price_ready=True,
            p2_normalized_sec_ready=True,
            point_in_time_market_cap_ready=False,
            corporate_action_history_ready=True,
            historical_news_classified_coverage=None,
        )
    )

    selection = select_best_eligible_experiment(
        assessments=assessments,
        ranked_experiments=("E6", "E5", "E3", "E2"),
    )

    assert selection.experiment_code == "E5"
    assert selection.status == "SELECTED"
    assert selection.reason == "BEST_ELIGIBLE_NON_LLM"
