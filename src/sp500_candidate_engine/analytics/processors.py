from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from sp500_candidate_engine.database import _canonical_hash


class ProcessorArtifactError(ValueError):
    """Raised when a processor artifact does not match its input."""


@dataclass(frozen=True)
class ProcessorArtifact:
    name: str
    fit_start: date
    fit_end: date
    feature_names: tuple[str, ...]
    means: tuple[float, ...]
    scales: tuple[float, ...]
    artifact_hash: str


def _date_index(frame: pd.DataFrame) -> pd.DatetimeIndex:
    if isinstance(frame.index, pd.MultiIndex):
        level = "datetime" if "datetime" in frame.index.names else 0
        return pd.DatetimeIndex(frame.index.get_level_values(level))
    return pd.DatetimeIndex(frame.index)


def fit_standardizer(
    frame: pd.DataFrame,
    *,
    fit_start: date,
    fit_end: date,
    name: str,
) -> ProcessorArtifact:
    if fit_start > fit_end:
        raise ValueError("fit_start must be on or before fit_end")
    if frame.empty:
        raise ProcessorArtifactError("Cannot fit a processor on an empty frame")
    dates = _date_index(frame)
    mask = (dates.date >= fit_start) & (dates.date <= fit_end)
    training = frame.loc[mask]
    if training.empty:
        raise ProcessorArtifactError("No rows fall within the processor fit period")
    numeric = training.to_numpy(dtype=float)
    if np.isinf(numeric).any():
        raise ProcessorArtifactError("Training features contain infinite values")
    means = np.nanmean(numeric, axis=0)
    scales = np.nanstd(numeric, axis=0)
    scales = np.where(np.isfinite(scales) & (scales > 0), scales, 1.0)
    if not np.isfinite(means).all():
        raise ProcessorArtifactError("A feature has no finite training values")
    payload = {
        "name": name,
        "fit_start": fit_start,
        "fit_end": fit_end,
        "feature_names": tuple(str(column) for column in frame.columns),
        "means": tuple(float(value) for value in means),
        "scales": tuple(float(value) for value in scales),
    }
    return ProcessorArtifact(
        **payload,
        artifact_hash=_canonical_hash(payload),
    )


def transform_with_artifact(
    frame: pd.DataFrame,
    artifact: ProcessorArtifact,
) -> pd.DataFrame:
    columns = tuple(str(column) for column in frame.columns)
    if columns != artifact.feature_names:
        raise ProcessorArtifactError("Feature columns or ordering do not match artifact")
    transformed = (
        frame.astype(float) - np.asarray(artifact.means)
    ) / np.asarray(artifact.scales)
    if np.isinf(transformed.to_numpy(dtype=float)).any():
        raise ProcessorArtifactError("Processed features contain infinite values")
    return transformed


def write_processor_artifact(artifact: ProcessorArtifact, path: Path) -> str:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(asdict(artifact), default=str, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return artifact.artifact_hash


def read_processor_artifact(path: Path) -> ProcessorArtifact:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    artifact = ProcessorArtifact(
        name=payload["name"],
        fit_start=date.fromisoformat(payload["fit_start"]),
        fit_end=date.fromisoformat(payload["fit_end"]),
        feature_names=tuple(payload["feature_names"]),
        means=tuple(float(value) for value in payload["means"]),
        scales=tuple(float(value) for value in payload["scales"]),
        artifact_hash=payload["artifact_hash"],
    )
    expected = _canonical_hash(
        {
            "name": artifact.name,
            "fit_start": artifact.fit_start,
            "fit_end": artifact.fit_end,
            "feature_names": artifact.feature_names,
            "means": artifact.means,
            "scales": artifact.scales,
        }
    )
    if expected != artifact.artifact_hash:
        raise ProcessorArtifactError("Processor artifact hash does not match its content")
    return artifact
