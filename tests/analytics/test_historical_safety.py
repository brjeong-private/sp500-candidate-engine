import uuid
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from sp500_candidate_engine.analytics.historical_safety import (
    HistoricalRunFence,
    HistoricalSafetyError,
    ModelArtifactEvidence,
    PointInTimeObservation,
    TrainingLabelEvidence,
    validate_historical_candidate_inputs,
)


def _valid_inputs() -> dict[str, object]:
    cutoff = datetime(2026, 1, 31, 12, tzinfo=UTC)
    snapshot_id = uuid.uuid4()
    fit_at = cutoff - timedelta(days=2)
    return {
        "fence": HistoricalRunFence(
            execution_context_id=uuid.uuid4(),
            input_manifest_id=uuid.uuid4(),
            target_session=date(2026, 1, 30),
            cutoff_at=cutoff,
        ),
        "manifest_snapshot_ids": frozenset({snapshot_id}),
        "observations": (
            PointInTimeObservation(
                source_snapshot_id=snapshot_id,
                source_available_at=cutoff - timedelta(hours=2),
                observed_at=cutoff - timedelta(hours=1),
            ),
        ),
        "training_labels": (
            TrainingLabelEvidence(
                anchor_session=date(2025, 12, 1),
                exit_session=date(2025, 12, 29),
                label_available_at=fit_at - timedelta(days=1),
            ),
        ),
        "model_artifact": ModelArtifactEvidence(
            model_version_id=uuid.uuid4(),
            fit_at=fit_at,
            artifact_created_at=fit_at + timedelta(hours=1),
        ),
    }


def test_historical_guard_accepts_only_cutoff_manifest_inputs() -> None:
    validate_historical_candidate_inputs(**_valid_inputs())  # type: ignore[arg-type]


def test_historical_guard_rejects_future_observation() -> None:
    inputs = _valid_inputs()
    fence = inputs["fence"]
    assert isinstance(fence, HistoricalRunFence)
    observation = inputs["observations"][0]  # type: ignore[index]
    inputs["observations"] = (
        PointInTimeObservation(
            source_snapshot_id=observation.source_snapshot_id,
            source_available_at=observation.source_available_at,
            observed_at=fence.cutoff_at + timedelta(seconds=1),
        ),
    )

    with pytest.raises(HistoricalSafetyError, match="future observation"):
        validate_historical_candidate_inputs(**inputs)  # type: ignore[arg-type]


def test_historical_guard_rejects_snapshot_outside_date_manifest() -> None:
    inputs = _valid_inputs()
    inputs["manifest_snapshot_ids"] = frozenset({uuid.uuid4()})

    with pytest.raises(HistoricalSafetyError, match="outside"):
        validate_historical_candidate_inputs(**inputs)  # type: ignore[arg-type]


def test_historical_guard_rejects_future_source_revision() -> None:
    inputs = _valid_inputs()
    fence = inputs["fence"]
    observation = inputs["observations"][0]  # type: ignore[index]
    assert isinstance(fence, HistoricalRunFence)
    inputs["observations"] = (
        PointInTimeObservation(
            source_snapshot_id=observation.source_snapshot_id,
            source_available_at=fence.cutoff_at + timedelta(seconds=1),
            observed_at=observation.observed_at,
        ),
    )

    with pytest.raises(HistoricalSafetyError, match="future source revision"):
        validate_historical_candidate_inputs(**inputs)  # type: ignore[arg-type]


def test_historical_guard_rejects_unmatured_training_label() -> None:
    inputs = _valid_inputs()
    artifact = inputs["model_artifact"]
    assert isinstance(artifact, ModelArtifactEvidence)
    inputs["training_labels"] = (
        TrainingLabelEvidence(
            anchor_session=date(2025, 12, 1),
            exit_session=date(2025, 12, 29),
            label_available_at=artifact.fit_at + timedelta(seconds=1),
        ),
    )

    with pytest.raises(HistoricalSafetyError, match="not matured"):
        validate_historical_candidate_inputs(**inputs)  # type: ignore[arg-type]


def test_historical_guard_rejects_future_model_artifact() -> None:
    inputs = _valid_inputs()
    fence = inputs["fence"]
    artifact = inputs["model_artifact"]
    assert isinstance(fence, HistoricalRunFence)
    assert isinstance(artifact, ModelArtifactEvidence)
    inputs["model_artifact"] = ModelArtifactEvidence(
        model_version_id=artifact.model_version_id,
        fit_at=artifact.fit_at,
        artifact_created_at=fence.cutoff_at + timedelta(seconds=1),
    )

    with pytest.raises(HistoricalSafetyError, match="future model artifact"):
        validate_historical_candidate_inputs(**inputs)  # type: ignore[arg-type]


def _reconstruction_inputs() -> dict[str, object]:
    inputs = _valid_inputs()
    artifact = inputs["model_artifact"]
    assert isinstance(artifact, ModelArtifactEvidence)
    training_cutoff = artifact.fit_at
    actual_fit_at = datetime(2026, 10, 18, tzinfo=UTC)
    inputs["knowledge_mode"] = "HISTORICAL_RECONSTRUCTION"
    inputs["model_artifact"] = replace(
        artifact,
        fit_at=actual_fit_at,
        artifact_created_at=actual_fit_at + timedelta(hours=1),
        reconstruction_training_cutoff=training_cutoff,
        training_data_end=date(2026, 1, 28),
        training_label_available_at=training_cutoff,
        processor_fit_data_end=date(2026, 1, 2),
    )
    observation = inputs["observations"][0]  # type: ignore[index]
    inputs["observations"] = (replace(observation, observed_at=actual_fit_at),)
    return inputs


def test_reconstruction_preserves_real_timestamps_and_allows_late_acquisition() -> None:
    inputs = _reconstruction_inputs()
    artifact = inputs["model_artifact"]
    validate_historical_candidate_inputs(**inputs)  # type: ignore[arg-type]
    assert artifact is inputs["model_artifact"]
    assert artifact.fit_at == datetime(2026, 10, 18, tzinfo=UTC)


def test_reconstruction_is_never_operational_replay() -> None:
    inputs = _reconstruction_inputs()
    inputs["knowledge_mode"] = "OPERATIONAL_REPLAY"
    inputs["observations"] = ()
    with pytest.raises(HistoricalSafetyError, match="not operational replay"):
        validate_historical_candidate_inputs(**inputs)  # type: ignore[arg-type]


@pytest.mark.parametrize("changes", [
    {"training_data_end": date(2026, 2, 1)},
    {"processor_fit_data_end": date(2026, 2, 1)},
    {"training_label_available_at": datetime(2026, 2, 1, tzinfo=UTC)},
    {"training_data_end": None},
    {"fit_at": datetime(2026, 1, 1, tzinfo=UTC)},
])
def test_reconstruction_rejects_future_or_missing_training_proof(
    changes: dict[str, object],
) -> None:
    inputs = _reconstruction_inputs()
    inputs["model_artifact"] = replace(inputs["model_artifact"], **changes)
    with pytest.raises(HistoricalSafetyError):
        validate_historical_candidate_inputs(**inputs)  # type: ignore[arg-type]


def test_training_label_must_mature_at_historical_cutoff_not_actual_fit() -> None:
    inputs = _reconstruction_inputs()
    inputs["training_labels"] = (TrainingLabelEvidence(
        anchor_session=date(2026, 1, 1),
        exit_session=date(2026, 1, 30),
        label_available_at=datetime(2026, 1, 30, tzinfo=UTC),
    ),)
    with pytest.raises(HistoricalSafetyError, match="not matured"):
        validate_historical_candidate_inputs(**inputs)  # type: ignore[arg-type]
