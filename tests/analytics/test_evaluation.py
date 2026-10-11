import pandas as pd
import pytest

from sp500_candidate_engine.analytics.evaluation import (
    WalkForwardSpec,
    build_walk_forward_folds,
    dedupe_walk_forward_predictions,
    evaluate_predictions,
)


def test_walk_forward_folds_are_time_ordered_and_non_overlapping() -> None:
    dates = tuple(pd.bdate_range("2025-01-01", periods=190))
    folds = build_walk_forward_folds(
        dates,
        WalkForwardSpec(
            minimum_train_sessions=100,
            validation_sessions=30,
            test_sessions=30,
            step_sessions=30,
            minimum_test_sessions=20,
        ),
    )

    assert len(folds) == 2
    assert folds[0].train_end < folds[0].valid_start
    assert folds[0].valid_end < folds[0].test_start
    assert folds[0].test_end < folds[1].test_start


def test_prediction_metrics_include_rank_ic_and_top_k_return() -> None:
    index = pd.MultiIndex.from_tuples(
        [
            (pd.Timestamp("2026-01-02"), "IA"),
            (pd.Timestamp("2026-01-02"), "IB"),
            (pd.Timestamp("2026-01-05"), "IA"),
            (pd.Timestamp("2026-01-05"), "IB"),
        ],
        names=["datetime", "instrument"],
    )
    predictions = pd.Series([2.0, 1.0, 1.0, 2.0], index=index)
    labels = pd.Series([0.2, -0.1, -0.2, 0.3], index=index)

    metrics = evaluate_predictions(predictions, labels, top_k=10, min_cross_section=2)

    assert metrics.rank_ic_mean == pytest.approx(1.0)
    assert metrics.top_5_return == pytest.approx(0.05)
    assert metrics.top_10_return == pytest.approx(0.05)
    assert metrics.positive_return_ratio_top_5 == pytest.approx(0.5)


def test_overlapping_predictions_keep_earliest_fold_for_each_date_instrument() -> None:
    frame = pd.DataFrame(
        {
            "datetime": pd.to_datetime(["2026-01-02", "2026-01-02"]),
            "instrument": ["IA", "IA"],
            "fold": [1, 2],
            "score": [0.1, 0.9],
        }
    )

    result = dedupe_walk_forward_predictions(frame)

    assert len(result) == 1
    assert result.iloc[0]["fold"] == 1


def test_twenty_session_walk_forward_uses_full_forty_session_windows() -> None:
    dates = tuple(pd.bdate_range("2025-01-01", periods=220))

    folds = build_walk_forward_folds(
        dates,
        WalkForwardSpec(
            minimum_train_sessions=100,
            validation_sessions=40,
            test_sessions=40,
            step_sessions=20,
            minimum_test_sessions=40,
        ),
    )

    assert len(folds) == 3
    assert all((fold.valid_end - fold.valid_start).days >= 39 for fold in folds)
    assert all((fold.test_end - fold.test_start).days >= 39 for fold in folds)
    assert folds[1].train_end == dates[119]
