from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime


class HistoricalSafetyError(ValueError):
    """Raised when a historical candidate run would use future knowledge."""


@dataclass(frozen=True)
class HistoricalRunFence:
    execution_context_id: uuid.UUID
    input_manifest_id: uuid.UUID
    target_session: date
    cutoff_at: datetime


@dataclass(frozen=True)
class PointInTimeObservation:
    source_snapshot_id: uuid.UUID
    source_available_at: datetime
    observed_at: datetime


@dataclass(frozen=True)
class TrainingLabelEvidence:
    anchor_session: date
    exit_session: date
    label_available_at: datetime


@dataclass(frozen=True)
class ModelArtifactEvidence:
    model_version_id: uuid.UUID
    fit_at: datetime
    artifact_created_at: datetime


def validate_historical_candidate_inputs(
    *,
    fence: HistoricalRunFence,
    manifest_snapshot_ids: frozenset[uuid.UUID],
    observations: tuple[PointInTimeObservation, ...],
    training_labels: tuple[TrainingLabelEvidence, ...],
    model_artifact: ModelArtifactEvidence,
) -> None:
    if not fence.execution_context_id or not fence.input_manifest_id:
        raise HistoricalSafetyError("date-specific execution context is required")
    if fence.cutoff_at.date() < fence.target_session:
        raise HistoricalSafetyError("cutoff precedes target session")
    if not manifest_snapshot_ids:
        raise HistoricalSafetyError("date-specific manifest is empty")

    for observation in observations:
        if observation.source_snapshot_id not in manifest_snapshot_ids:
            raise HistoricalSafetyError("observation is outside the date-specific manifest")
        if observation.source_available_at > fence.cutoff_at:
            raise HistoricalSafetyError("future source revision is not allowed")
        if observation.observed_at > fence.cutoff_at:
            raise HistoricalSafetyError("future observation is not allowed")

    if model_artifact.fit_at > fence.cutoff_at:
        raise HistoricalSafetyError("model fit is after candidate cutoff")
    if model_artifact.artifact_created_at > fence.cutoff_at:
        raise HistoricalSafetyError("future model artifact is not allowed")
    for label in training_labels:
        if label.exit_session < label.anchor_session:
            raise HistoricalSafetyError("label exit precedes anchor")
        if label.label_available_at > model_artifact.fit_at:
            raise HistoricalSafetyError("training label had not matured by fit_at")
