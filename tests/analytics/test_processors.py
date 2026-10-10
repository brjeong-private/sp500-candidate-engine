from datetime import date

import pandas as pd
import pytest

from sp500_candidate_engine.analytics.processors import (
    ProcessorArtifactError,
    fit_standardizer,
    transform_with_artifact,
)


def test_processor_fits_only_requested_training_period() -> None:
    frame = pd.DataFrame(
        {"F1": [1.0, 3.0, 1000.0], "F2": [2.0, 4.0, 2000.0]},
        index=pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06"]),
    )

    artifact = fit_standardizer(
        frame,
        fit_start=date(2026, 1, 2),
        fit_end=date(2026, 1, 5),
        name="standard-v1",
    )
    transformed = transform_with_artifact(frame, artifact)

    assert artifact.means == pytest.approx((2.0, 3.0))
    assert transformed.loc["2026-01-02", "F1"] == pytest.approx(-1.0)
    assert transformed.loc["2026-01-05", "F1"] == pytest.approx(1.0)
    assert len(artifact.artifact_hash) == 64


def test_processor_rejects_feature_order_mismatch() -> None:
    frame = pd.DataFrame(
        {"F1": [1.0, 2.0], "F2": [3.0, 4.0]},
        index=pd.to_datetime(["2026-01-02", "2026-01-05"]),
    )
    artifact = fit_standardizer(
        frame,
        fit_start=date(2026, 1, 2),
        fit_end=date(2026, 1, 5),
        name="standard-v1",
    )

    with pytest.raises(ProcessorArtifactError, match="Feature columns"):
        transform_with_artifact(frame[["F2", "F1"]], artifact)
