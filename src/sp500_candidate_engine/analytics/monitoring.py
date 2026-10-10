from __future__ import annotations

import numpy as np
import pandas as pd


def population_stability_index(
    reference: pd.Series,
    current: pd.Series,
    *,
    bins: int = 10,
) -> float:
    reference = reference.replace([np.inf, -np.inf], np.nan).dropna()
    current = current.replace([np.inf, -np.inf], np.nan).dropna()
    if reference.empty or current.empty:
        raise ValueError("PSI requires finite reference and current values")
    boundaries = np.unique(
        np.quantile(reference.to_numpy(dtype=float), np.linspace(0, 1, bins + 1))
    )
    if len(boundaries) < 3:
        return 0.0
    boundaries[0] = -np.inf
    boundaries[-1] = np.inf
    reference_share = (
        pd.cut(reference, boundaries, include_lowest=True).value_counts(normalize=True)
    )
    current_share = (
        pd.cut(current, boundaries, include_lowest=True).value_counts(normalize=True)
    )
    epsilon = 1e-6
    expected = reference_share.clip(lower=epsilon)
    actual = current_share.reindex(expected.index, fill_value=epsilon).clip(lower=epsilon)
    return float(((actual - expected) * np.log(actual / expected)).sum())


def score_distribution_summary(scores: pd.Series) -> dict[str, float]:
    finite = scores.replace([np.inf, -np.inf], np.nan).dropna()
    if finite.empty:
        raise ValueError("No finite scores")
    return {
        "count": float(len(finite)),
        "mean": float(finite.mean()),
        "std": float(finite.std(ddof=0)),
        "minimum": float(finite.min()),
        "maximum": float(finite.max()),
    }
