import pandas as pd

from sp500_candidate_engine.analytics.monitoring import (
    population_stability_index,
    score_distribution_summary,
)


def test_monitoring_detects_distribution_shift() -> None:
    reference = pd.Series(range(100), dtype=float)
    same = population_stability_index(reference, reference)
    shifted = population_stability_index(reference, reference + 100)

    assert same == 0
    assert shifted > same
    assert score_distribution_summary(reference)["count"] == 100
