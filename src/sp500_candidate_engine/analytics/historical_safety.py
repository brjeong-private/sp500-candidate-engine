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
    reconstruction_training_cutoff: datetime | None = None
    training_data_end: date | None = None
    training_label_available_at: datetime | None = None
    processor_fit_data_end: date | None = None


@dataclass(frozen=True)
class HistoricalTrainingFence:
    """A knowledge boundary, never a substitute for the actual wall-clock fit time."""

    anchor_session: date
    training_cutoff: datetime

    def validate(self) -> None:
        if self.training_cutoff.utcoffset() is None:
            raise HistoricalSafetyError("training cutoff must be timezone-aware")
        if self.anchor_session >= self.training_cutoff.date():
            raise HistoricalSafetyError("training cutoff must follow the anchor session")


def validate_historical_candidate_inputs(
    *,
    fence: HistoricalRunFence,
    manifest_snapshot_ids: frozenset[uuid.UUID],
    observations: tuple[PointInTimeObservation, ...],
    training_labels: tuple[TrainingLabelEvidence, ...],
    model_artifact: ModelArtifactEvidence,
    knowledge_mode: str = "OPERATIONAL_REPLAY",
) -> None:
    if knowledge_mode not in {"OPERATIONAL_REPLAY", "HISTORICAL_RECONSTRUCTION"}:
        raise HistoricalSafetyError("unsupported knowledge mode")
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
        if (
            knowledge_mode == "OPERATIONAL_REPLAY"
            and observation.observed_at > fence.cutoff_at
        ):
            raise HistoricalSafetyError("future observation is not allowed")

    training_cutoff = model_artifact.fit_at
    reconstruction_cutoff = model_artifact.reconstruction_training_cutoff
    if reconstruction_cutoff is None:
        if model_artifact.fit_at > fence.cutoff_at:
            raise HistoricalSafetyError("model fit is after candidate cutoff")
        if model_artifact.artifact_created_at > fence.cutoff_at:
            raise HistoricalSafetyError("future model artifact is not allowed")
    else:
        if knowledge_mode != "HISTORICAL_RECONSTRUCTION":
            raise HistoricalSafetyError("reconstructed artifact is not operational replay")
        if reconstruction_cutoff >= fence.cutoff_at:
            raise HistoricalSafetyError("training cutoff must precede candidate cutoff")
        if model_artifact.artifact_created_at < model_artifact.fit_at:
            raise HistoricalSafetyError("artifact creation precedes actual fit")
        if model_artifact.fit_at <= reconstruction_cutoff:
            raise HistoricalSafetyError("reconstruction must preserve actual fit time")
        if (
            model_artifact.training_data_end is None
            or model_artifact.processor_fit_data_end is None
            or model_artifact.training_label_available_at is None
            or model_artifact.training_data_end > reconstruction_cutoff.date()
            or model_artifact.processor_fit_data_end > reconstruction_cutoff.date()
            or model_artifact.training_label_available_at > reconstruction_cutoff
        ):
            raise HistoricalSafetyError("reconstruction training evidence exceeds cutoff")
        training_cutoff = reconstruction_cutoff
    for label in training_labels:
        if label.exit_session < label.anchor_session:
            raise HistoricalSafetyError("label exit precedes anchor")
        if (
            label.label_available_at > training_cutoff
            or label.exit_session > training_cutoff.date()
        ):
            raise HistoricalSafetyError("training label had not matured by fit_at")
