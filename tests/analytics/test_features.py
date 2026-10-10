from datetime import date

import numpy as np
import pandas as pd
import pytest

from sp500_candidate_engine.analytics.features import (
    Alpha158FeatureError,
    Alpha158FeatureService,
)


class _Runtime:
    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame
        self.calls: list[dict[str, object]] = []

    def load_raw_features(self, **kwargs: object) -> pd.DataFrame:
        self.calls.append(kwargs)
        return self.frame


def _frame(columns: int = 158) -> pd.DataFrame:
    index = pd.MultiIndex.from_tuples(
        [(pd.Timestamp("2026-01-02"), "TEST")],
        names=["datetime", "instrument"],
    )
    return pd.DataFrame(
        np.arange(columns, dtype=float).reshape(1, columns),
        index=index,
        columns=[f"F{number:03d}" for number in range(columns)],
    )


def test_alpha158_service_accepts_exact_raw_dimension() -> None:
    runtime = _Runtime(_frame())
    service = Alpha158FeatureService(runtime=runtime)

    result = service.compute_raw(
        provider_uri="qlib-data",
        instruments="all",
        start_date=date(2026, 1, 2),
        end_date=date(2026, 1, 2),
    )

    assert result.expected_dimension == 158
    assert result.feature_names[0] == "F000"
    assert runtime.calls[0]["infer_processors"] == []
    assert runtime.calls[0]["learn_processors"] == []


def test_alpha158_service_blocks_dimension_mismatch() -> None:
    service = Alpha158FeatureService(runtime=_Runtime(_frame(157)))

    with pytest.raises(Alpha158FeatureError, match="Expected 158"):
        service.compute_raw(
            provider_uri="qlib-data",
            instruments="all",
            start_date=date(2026, 1, 2),
            end_date=date(2026, 1, 2),
        )


def test_alpha158_service_blocks_infinity() -> None:
    frame = _frame()
    frame.iloc[0, 0] = np.inf
    service = Alpha158FeatureService(runtime=_Runtime(frame))

    with pytest.raises(Alpha158FeatureError, match="infinite"):
        service.compute_raw(
            provider_uri="qlib-data",
            instruments="all",
            start_date=date(2026, 1, 2),
            end_date=date(2026, 1, 2),
        )
