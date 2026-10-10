from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class WalkForwardSpec:
    minimum_train_sessions: int
    validation_sessions: int
    test_sessions: int
    step_sessions: int
    minimum_test_sessions: int


@dataclass(frozen=True)
class WalkForwardFold:
    fold: int
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    valid_start: pd.Timestamp
    valid_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp


@dataclass(frozen=True)
class PredictionMetrics:
    observations: int
    dates: int
    ic_mean: float
    rank_ic_mean: float
    rank_ic_ir: float
    top_5_return: float
    top_10_return: float
    positive_return_ratio_top_5: float
    positive_return_ratio_top_10: float
    net_top_5_return: float
    net_top_10_return: float
    max_drawdown_top_5: float
    max_drawdown_top_10: float
    coverage: float


def build_walk_forward_folds(
    dates: tuple[pd.Timestamp, ...],
    spec: WalkForwardSpec,
) -> tuple[WalkForwardFold, ...]:
    ordered = tuple(sorted(set(pd.Timestamp(value) for value in dates)))
    folds: list[WalkForwardFold] = []
    train_sessions = spec.minimum_train_sessions
    fold_number = 1
    while True:
        valid_start_index = train_sessions
        valid_end_index = valid_start_index + spec.validation_sessions
        test_start_index = valid_end_index
        if test_start_index >= len(ordered):
            break
        test_end_index = min(test_start_index + spec.test_sessions, len(ordered))
        if test_end_index - test_start_index < spec.minimum_test_sessions:
            break
        folds.append(
            WalkForwardFold(
                fold=fold_number,
                train_start=ordered[0],
                train_end=ordered[valid_start_index - 1],
                valid_start=ordered[valid_start_index],
                valid_end=ordered[valid_end_index - 1],
                test_start=ordered[test_start_index],
                test_end=ordered[test_end_index - 1],
            )
        )
        train_sessions += spec.step_sessions
        fold_number += 1
    if not folds:
        raise ValueError("Insufficient sessions for the configured walk-forward split")
    return tuple(folds)


def evaluate_predictions(
    predictions: pd.Series,
    labels: pd.Series,
    *,
    top_k: int,
    min_cross_section: int,
    round_trip_cost_bps: float = 10,
    holding_period_sessions: int = 5,
) -> PredictionMetrics:
    joined = pd.concat(
        [predictions.rename("score"), labels.rename("label")],
        axis=1,
        join="inner",
    ).dropna()
    if joined.empty:
        raise ValueError("No overlapping prediction and label rows")
    daily_ic: list[float] = []
    daily_rank_ic: list[float] = []
    top_5_returns: list[float] = []
    top_10_returns: list[float] = []
    top_5_values: list[float] = []
    top_10_values: list[float] = []
    for _, frame in joined.groupby(level="datetime", sort=True):
        if len(frame) >= min_cross_section:
            daily_ic.append(float(frame["score"].corr(frame["label"], method="pearson")))
            daily_rank_ic.append(
                float(
                    frame["score"].rank(method="average").corr(
                        frame["label"].rank(method="average"),
                        method="pearson",
                    )
                )
            )
        ordered = frame.sort_values(
            ["score"],
            ascending=False,
            kind="mergesort",
        )
        top_5 = ordered.head(min(5, top_k))
        top_10 = ordered.head(min(10, top_k))
        if not top_5.empty:
            top_5_returns.append(float(top_5["label"].mean()))
            top_5_values.extend(float(value) for value in top_5["label"])
        if not top_10.empty:
            top_10_returns.append(float(top_10["label"].mean()))
            top_10_values.extend(float(value) for value in top_10["label"])
    rank_values = np.asarray(daily_rank_ic, dtype=float)
    rank_std = float(np.nanstd(rank_values, ddof=1)) if len(rank_values) > 1 else np.nan
    rank_mean = float(np.nanmean(rank_values)) if len(rank_values) else np.nan
    cost = round_trip_cost_bps / 10_000

    def net_mean(values: list[float]) -> float:
        return float(np.mean(np.asarray(values) - cost)) if values else np.nan

    def overlapping_max_drawdown(values: list[float]) -> float:
        if not values:
            return np.nan
        cohort_contribution = (np.asarray(values) - cost) / holding_period_sessions
        equity = np.cumprod(1 + cohort_contribution)
        drawdown = equity / np.maximum.accumulate(equity) - 1
        return float(drawdown.min())

    return PredictionMetrics(
        observations=len(joined),
        dates=joined.index.get_level_values("datetime").nunique(),
        ic_mean=float(np.nanmean(daily_ic)) if daily_ic else np.nan,
        rank_ic_mean=rank_mean,
        rank_ic_ir=rank_mean / rank_std if rank_std and np.isfinite(rank_std) else np.nan,
        top_5_return=float(np.mean(top_5_returns)) if top_5_returns else np.nan,
        top_10_return=float(np.mean(top_10_returns)) if top_10_returns else np.nan,
        positive_return_ratio_top_5=(
            float(np.mean(np.asarray(top_5_values) > 0)) if top_5_values else np.nan
        ),
        positive_return_ratio_top_10=(
            float(np.mean(np.asarray(top_10_values) > 0)) if top_10_values else np.nan
        ),
        net_top_5_return=net_mean(top_5_returns),
        net_top_10_return=net_mean(top_10_returns),
        max_drawdown_top_5=overlapping_max_drawdown(top_5_returns),
        max_drawdown_top_10=overlapping_max_drawdown(top_10_returns),
        coverage=len(joined) / len(labels),
    )


def dedupe_walk_forward_predictions(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"datetime", "instrument", "fold"}
    if not required.issubset(frame.columns):
        raise ValueError(f"Prediction frame is missing {sorted(required - set(frame.columns))}")
    identity = ["datetime", "instrument"]
    if "model" in frame.columns:
        identity.append("model")
    return (
        frame.sort_values([*identity, "fold"], kind="mergesort")
        .drop_duplicates(identity, keep="first")
        .reset_index(drop=True)
    )
