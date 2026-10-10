from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from importlib import import_module
from pathlib import Path
from typing import Protocol

import numpy as np
import pandas as pd


class Alpha158FeatureError(ValueError):
    """Raised when Qlib Alpha158 output violates the feature contract."""


class Alpha158RuntimeUnavailable(RuntimeError):
    """Raised when the optional Qlib runtime is not installed."""


class Alpha158Runtime(Protocol):
    def load_raw_features(
        self,
        *,
        provider_uri: str | Path,
        instruments: str,
        start_date: date,
        end_date: date,
        infer_processors: list[object],
        learn_processors: list[object],
    ) -> pd.DataFrame: ...


class QlibAlpha158Runtime:
    def load_raw_features(
        self,
        *,
        provider_uri: str | Path,
        instruments: str,
        start_date: date,
        end_date: date,
        infer_processors: list[object],
        learn_processors: list[object],
    ) -> pd.DataFrame:
        try:
            qlib = import_module("qlib")
            config_module = import_module("qlib.config")
            handler_module = import_module("qlib.contrib.data.handler")
            data_handler_module = import_module("qlib.data.dataset.handler")
        except ImportError as exc:
            raise Alpha158RuntimeUnavailable(
                "Install the analytics extra in a Python 3.11 or 3.12 environment"
            ) from exc

        alpha158_class = handler_module.Alpha158
        data_handler_class = data_handler_module.DataHandlerLP
        qlib.init(
            provider_uri=str(provider_uri),
            region=config_module.REG_US,
            kernels=1,
        )
        handler = alpha158_class(
            instruments=instruments,
            start_time=start_date.isoformat(),
            end_time=end_date.isoformat(),
            fit_start_time=start_date.isoformat(),
            fit_end_time=end_date.isoformat(),
            infer_processors=infer_processors,
            learn_processors=learn_processors,
        )
        frame = handler.fetch(
            selector=slice(start_date.isoformat(), end_date.isoformat()),
            level="datetime",
            col_set="feature",
            data_key=data_handler_class.DK_R,
        )
        if not isinstance(frame, pd.DataFrame):
            raise Alpha158FeatureError("Qlib Alpha158 did not return a DataFrame")
        return frame


@dataclass(frozen=True)
class Alpha158FeatureResult:
    frame: pd.DataFrame
    feature_names: tuple[str, ...]
    expected_dimension: int


class Alpha158FeatureService:
    EXPECTED_DIMENSION = 158

    def __init__(self, runtime: Alpha158Runtime | None = None) -> None:
        self.runtime = runtime or QlibAlpha158Runtime()

    def compute_raw(
        self,
        *,
        provider_uri: str | Path,
        instruments: str,
        start_date: date,
        end_date: date,
    ) -> Alpha158FeatureResult:
        if start_date > end_date:
            raise ValueError("start_date must be on or before end_date")
        frame = self.runtime.load_raw_features(
            provider_uri=provider_uri,
            instruments=instruments,
            start_date=start_date,
            end_date=end_date,
            infer_processors=[],
            learn_processors=[],
        )
        if frame.shape[1] != self.EXPECTED_DIMENSION:
            raise Alpha158FeatureError(
                f"Expected 158 Alpha158 features, got {frame.shape[1]}"
            )
        numeric = frame.to_numpy(dtype=float)
        if np.isinf(numeric).any():
            raise Alpha158FeatureError("Alpha158 output contains infinite values")
        if frame.index.has_duplicates:
            raise Alpha158FeatureError("Alpha158 output index contains duplicates")
        feature_names = tuple(str(column) for column in frame.columns)
        return Alpha158FeatureResult(
            frame=frame.sort_index(),
            feature_names=feature_names,
            expected_dimension=self.EXPECTED_DIMENSION,
        )


def normalize_alpha158_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(frame.index, pd.MultiIndex) or frame.index.nlevels != 2:
        raise Alpha158FeatureError("Alpha158 index must be a two-level MultiIndex")
    index_frame = frame.index.to_frame(index=False)
    datetime_column = next(
        (
            column
            for column in index_frame
            if str(column).lower() in {"datetime", "date"}
        ),
        None,
    )
    if datetime_column is None:
        scores = {
            column: pd.to_datetime(index_frame[column], errors="coerce").notna().mean()
            for column in index_frame
        }
        datetime_column = max(scores, key=scores.get)
        if scores[datetime_column] < 0.95:
            raise Alpha158FeatureError("Cannot identify Alpha158 datetime index level")
    instrument_column = next(
        column for column in index_frame if column != datetime_column
    )
    flat = frame.reset_index().rename(
        columns={
            datetime_column: "datetime",
            instrument_column: "instrument",
        }
    )
    flat["datetime"] = pd.to_datetime(flat["datetime"])
    flat["instrument"] = flat["instrument"].astype(str).str.upper()
    feature_columns = [
        column for column in flat.columns if column not in {"datetime", "instrument"}
    ]
    result = flat.set_index(["datetime", "instrument"])[feature_columns].sort_index()
    result.columns = [
        str(column[-1] if isinstance(column, tuple) else column)
        for column in result.columns
    ]
    if result.columns.duplicated().any():
        raise Alpha158FeatureError("Alpha158 feature names are duplicated")
    return result
