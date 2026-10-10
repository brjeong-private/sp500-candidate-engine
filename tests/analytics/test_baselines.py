import pandas as pd
import pytest

from sp500_candidate_engine.analytics.baselines import compute_momentum_scores


def test_momentum_uses_exact_session_lookback_without_fill() -> None:
    index = pd.MultiIndex.from_product(
        [
            pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06"]),
            ["IA", "IB"],
        ],
        names=["datetime", "instrument"],
    )
    close = pd.Series([10.0, 20.0, 11.0, 20.0, 12.0, 18.0], index=index)

    scores = compute_momentum_scores(close, lookback_sessions=2)

    assert scores.loc[(pd.Timestamp("2026-01-06"), "IA")] == pytest.approx(0.2)
    assert scores.loc[(pd.Timestamp("2026-01-06"), "IB")] == pytest.approx(-0.1)
    assert pd.isna(scores.loc[(pd.Timestamp("2026-01-02"), "IA")])
