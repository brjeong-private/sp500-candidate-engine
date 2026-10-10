from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from unittest.mock import patch

import pandas as pd


class FrameDataset:
    def __init__(
        self,
        *,
        features: pd.DataFrame,
        labels: pd.Series,
        segments: dict[str, pd.Index],
    ) -> None:
        self.features = features
        self.labels = labels
        self.segments = segments

    def prepare(
        self,
        segment: str,
        *,
        col_set: str | list[str],
        data_key: object,
    ) -> pd.DataFrame:
        del data_key
        index = self.segments[segment]
        feature_frame = self.features.loc[index]
        if col_set == "feature":
            return feature_frame
        if col_set == "label":
            return self.labels.loc[index].to_frame("LABEL0")
        requested = [col_set] if isinstance(col_set, str) else col_set
        parts: dict[str, pd.DataFrame] = {}
        if "feature" in requested:
            parts["feature"] = feature_frame
        if "label" in requested:
            parts["label"] = self.labels.loc[index].to_frame("LABEL0")
        return pd.concat(parts, axis=1)


@dataclass
class TrainedQlibLightGBM:
    model: object
    evals_result: dict[str, object]

    def predict(self, features: pd.DataFrame) -> pd.Series:
        booster = self.model.model  # type: ignore[attr-defined]
        return pd.Series(
            booster.predict(features.to_numpy()),  # type: ignore[union-attr]
            index=features.index,
            name="score",
        )

    def save(self, path: Path) -> None:
        booster = self.model.model  # type: ignore[attr-defined]
        if booster is None:
            raise RuntimeError("LightGBM booster is missing")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        booster.save_model(str(path))  # type: ignore[union-attr]


def train_qlib_lightgbm(
    *,
    features: pd.DataFrame,
    labels: pd.Series,
    train_index: pd.Index,
    valid_index: pd.Index,
    parameters: dict[str, object],
) -> TrainedQlibLightGBM:
    try:
        gbdt_module = import_module("qlib.contrib.model.gbdt")
        workflow_module = import_module("qlib.workflow")
    except ImportError as exc:
        raise RuntimeError("Qlib analytics environment is required") from exc
    params = dict(parameters)
    num_boost_round = int(params.pop("num_boost_round", 300))
    early_stopping_rounds = int(params.pop("early_stopping_rounds", 30))
    loss = str(params.pop("loss", "mse"))
    dataset = FrameDataset(
        features=features,
        labels=labels,
        segments={"train": train_index, "valid": valid_index},
    )
    model = gbdt_module.LGBModel(
        loss=loss,
        num_boost_round=num_boost_round,
        early_stopping_rounds=early_stopping_rounds,
        **params,
    )
    evals_result: dict[str, object] = {}
    with patch.object(
        workflow_module.R,
        "log_metrics",
        return_value=None,
        create=True,
    ):
        model.fit(dataset, verbose_eval=0, evals_result=evals_result)
    return TrainedQlibLightGBM(model=model, evals_result=evals_result)
