"""Data-only serving for the fitted median-imputer / scaler / Ridge pipeline."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

RIDGE_FILE_NAME = "ridge.json"
RIDGE_FORMAT = "median-standard-scaler-ridge-v1"
MAX_RIDGE_BYTES = 2 * 1024 * 1024


def _array(value: object, dimension: int, dtype: str) -> np.ndarray:
    if dtype not in {"float32", "float64"}:
        raise ValueError("Unsupported fitted Ridge dtype")
    if (
        not isinstance(value, list)
        or len(value) != dimension
        or any(type(item) not in (int, float) for item in value)
    ):
        raise ValueError("Ridge array dimension/type mismatch")
    result = np.asarray(value, dtype=dtype)
    if not np.isfinite(result).all():
        raise ValueError("Nonfinite fitted Ridge array")
    result.setflags(write=False)
    return result


@dataclass(frozen=True)
class NumericRidge:
    feature_names: tuple[str, ...]
    training_artifact_sha256: str
    statistics: np.ndarray
    mean: np.ndarray
    scale: np.ndarray
    coefficient: np.ndarray
    intercept: np.ndarray

    def predict(self, features: pd.DataFrame) -> np.ndarray:
        if tuple(features.columns) != self.feature_names:
            raise ValueError("Ridge feature names/order mismatch")
        values = features.to_numpy(copy=True)
        if values.dtype.kind not in "fiu" or values.ndim != 2 or len(values) == 0:
            raise ValueError("Ridge requires a nonempty numeric feature matrix")
        # sklearn retains float32/float64 at each imputer/scaler operation.
        if values.dtype.kind == "f" and values.dtype not in (
            np.dtype("float32"), np.dtype("float64"),
        ):
            raise ValueError("Unsupported Ridge input floating dtype")
        if values.dtype not in (np.dtype("float32"), np.dtype("float64")):
            values = values.astype("float64")
        if np.isinf(values).any():
            raise ValueError("Infinite Ridge input")
        missing = np.isnan(values)
        values[missing] = np.broadcast_to(self.statistics, values.shape)[missing]
        values -= self.mean
        values /= self.scale
        prediction = values @ self.coefficient + self.intercept[0]
        if prediction.shape != (len(features),) or not np.isfinite(prediction).all():
            raise ValueError("Nonfinite or invalid Ridge predictions")
        return prediction

    def to_bytes(self) -> bytes:
        return (json.dumps({
            "format": RIDGE_FORMAT,
            "feature_names": list(self.feature_names),
            "training_artifact_sha256": self.training_artifact_sha256,
            "imputer": {
                "strategy": "median", "keep_empty_features": True, "add_indicator": False,
                "statistics_dtype": str(self.statistics.dtype),
                "statistics": self.statistics.tolist(),
            },
            "scaler": {
                "with_mean": True, "with_std": True,
                "mean": self.mean.tolist(), "scale": self.scale.tolist(),
            },
            "ridge": {
                "dtype": str(self.coefficient.dtype),
                "coefficient": self.coefficient.tolist(), "intercept": self.intercept.tolist(),
            },
        }, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()

    @classmethod
    def from_bytes(cls, content: bytes) -> NumericRidge:
        if len(content) > MAX_RIDGE_BYTES:
            raise ValueError("Ridge artifact exceeds size bound")
        value = json.loads(content)
        if not isinstance(value, dict) or set(value) != {
            "format", "feature_names", "training_artifact_sha256", "imputer", "scaler", "ridge",
        }:
            raise ValueError("Invalid numeric Ridge fields")
        names = value["feature_names"]
        digest = value["training_artifact_sha256"]
        if (
            value["format"] != RIDGE_FORMAT or not isinstance(names, list) or not names
            or any(not isinstance(name, str) or not name for name in names)
            or len(set(names)) != len(names) or len(names) > 10000
            or not isinstance(digest, str) or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
        ):
            raise ValueError("Invalid numeric Ridge identity")
        imputer, scaler, ridge = value["imputer"], value["scaler"], value["ridge"]
        if (
            not isinstance(imputer, dict) or set(imputer) != {
                "strategy", "keep_empty_features", "add_indicator",
                "statistics_dtype", "statistics",
            }
            or imputer["strategy"] != "median" or imputer["keep_empty_features"] is not True
            or imputer["add_indicator"] is not False
            or not isinstance(scaler, dict) or set(scaler) != {
                "with_mean", "with_std", "mean", "scale",
            }
            or scaler["with_mean"] is not True or scaler["with_std"] is not True
            or not isinstance(ridge, dict) or set(ridge) != {
                "dtype", "coefficient", "intercept",
            }
        ):
            raise ValueError("Unsupported Ridge preprocessing contract")
        dimension = len(names)
        model = cls(
            tuple(names), digest,
            _array(imputer["statistics"], dimension, imputer["statistics_dtype"]),
            _array(scaler["mean"], dimension, "float64"),
            _array(scaler["scale"], dimension, "float64"),
            _array(ridge["coefficient"], dimension, ridge["dtype"]),
            _array(ridge["intercept"], 1, ridge["dtype"]),
        )
        if (model.scale <= 0).any():
            raise ValueError("Ridge scale must be positive")
        return model

    @classmethod
    def load(cls, path: Path) -> NumericRidge:
        with path.open("rb") as stream:
            return cls.from_bytes(stream.read(MAX_RIDGE_BYTES + 1))


def export_fitted_ridge(
    pipeline: object, *, feature_names: tuple[str, ...], training_artifact_sha256: str,
) -> bytes:
    """Inspect an already trusted in-memory estimator; never deserialize pickle here."""
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    if type(pipeline) is not Pipeline or [name for name, _ in pipeline.steps] != [
        "imputer", "scaler", "model",
    ]:
        raise ValueError("Unsupported fitted Ridge pipeline")
    imputer, scaler, ridge = (step for _, step in pipeline.steps)
    if (
        type(imputer) is not SimpleImputer or type(scaler) is not StandardScaler
        or type(ridge) is not Ridge or imputer.strategy != "median"
        or imputer.keep_empty_features is not True or imputer.add_indicator
        or not np.isnan(imputer.missing_values)
        or scaler.with_mean is not True or scaler.with_std is not True
        or tuple(pipeline.feature_names_in_) != feature_names
        or any(step.n_features_in_ != len(feature_names) for step in (imputer, scaler, ridge))
        or ridge.coef_.ndim != 1 or np.ndim(ridge.intercept_) != 0
    ):
        raise ValueError("Unsupported fitted Ridge preprocessing or feature order")
    model = NumericRidge(
        feature_names, training_artifact_sha256, imputer.statistics_, scaler.mean_,
        scaler.scale_, ridge.coef_, np.asarray([ridge.intercept_], dtype=ridge.coef_.dtype),
    )
    content = model.to_bytes()
    NumericRidge.from_bytes(content)
    return content


def verify_ridge_parity(
    pipeline: object, model: NumericRidge, features: pd.DataFrame,
) -> dict[str, object]:
    """Compare real rows plus NaN/constant cases without fitting any processor."""
    if tuple(features.columns) != model.feature_names or features.empty:
        raise ValueError("Ridge parity requires real features in fitted order")
    real = pd.concat([features.head(128), features.tail(128)])
    worst = 0.0
    comparisons = 0
    for dtype in ("float32", "float64"):
        real_case = real.astype(dtype)
        synthetic = real_case.head(4).copy()
        synthetic.iloc[0, :] = np.nan
        synthetic.iloc[1, ::2] = np.nan
        synthetic.iloc[2, :] = 0
        for case in (real_case, synthetic):
            expected = np.asarray(pipeline.predict(case))  # type: ignore[attr-defined]
            actual = model.predict(case)
            if (
                expected.dtype != actual.dtype or expected.shape != actual.shape
                or not np.isfinite(expected).all()
                or not np.allclose(expected, actual, rtol=1e-6, atol=1e-7)
            ):
                raise ValueError("Numeric Ridge prediction parity failed")
            worst = max(worst, float(np.max(np.abs(expected - actual))))
            comparisons += len(case)
    return {
        "rows_compared": comparisons, "max_absolute_error": worst,
        "rtol": 1e-6, "atol": 1e-7,
        "cases": ["real", "all_nan", "partial_nan", "zero", "float32", "float64"],
    }
