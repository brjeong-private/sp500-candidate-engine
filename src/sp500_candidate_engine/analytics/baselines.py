from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from pathlib import Path

import pandas as pd


def compute_momentum_scores(
    adjusted_close: pd.Series,
    *,
    lookback_sessions: int,
) -> pd.Series:
    if lookback_sessions < 1:
        raise ValueError("lookback_sessions must be positive")
    if not isinstance(adjusted_close.index, pd.MultiIndex):
        raise ValueError("adjusted_close must use a datetime/instrument MultiIndex")
    if "instrument" not in adjusted_close.index.names:
        raise ValueError("adjusted_close index must include instrument")
    return adjusted_close.groupby(level="instrument", group_keys=False).transform(
        lambda series: series / series.shift(lookback_sessions) - 1
    )


@dataclass
class RidgeBaseline:
    alpha: float
    seed: int
    pipeline: object | None = None

    def fit(self, features: pd.DataFrame, labels: pd.Series) -> None:
        pipeline_module = import_module("sklearn.pipeline")
        impute_module = import_module("sklearn.impute")
        preprocessing_module = import_module("sklearn.preprocessing")
        linear_module = import_module("sklearn.linear_model")
        self.pipeline = pipeline_module.Pipeline(
            [
                (
                    "imputer",
                    impute_module.SimpleImputer(
                        strategy="median",
                        keep_empty_features=True,
                    ),
                ),
                ("scaler", preprocessing_module.StandardScaler()),
                (
                    "model",
                    linear_module.Ridge(alpha=self.alpha, random_state=self.seed),
                ),
            ]
        )
        self.pipeline.fit(features, labels)

    def predict(self, features: pd.DataFrame) -> pd.Series:
        if self.pipeline is None:
            raise RuntimeError("Ridge baseline is not fitted")
        values = self.pipeline.predict(features)  # type: ignore[attr-defined]
        return pd.Series(values, index=features.index, name="score")

    def save(self, path: Path) -> None:
        if self.pipeline is None:
            raise RuntimeError("Ridge baseline is not fitted")
        joblib = import_module("joblib")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self.pipeline, path)

    def save_numeric(self, path: Path, *, training_artifact_sha256: str) -> None:
        from sp500_candidate_engine.analytics.artifacts import _write_immutable
        from sp500_candidate_engine.analytics.ridge_artifact import export_fitted_ridge

        if self.pipeline is None:
            raise RuntimeError("Ridge baseline is not fitted")
        content = export_fitted_ridge(
            self.pipeline,
            feature_names=tuple(self.pipeline.feature_names_in_),  # type: ignore[attr-defined]
            training_artifact_sha256=training_artifact_sha256,
        )
        _write_immutable(Path(path), content)
