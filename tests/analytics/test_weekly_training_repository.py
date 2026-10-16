from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from unittest.mock import MagicMock

import pytest

from sp500_candidate_engine.analytics.weekly_training import (
    AssignmentGenerationConflict,
    WeeklyRunStateConflict,
    WeeklyTrainingRepository,
    weekly_run_id,
)


def test_weekly_run_id_is_deterministic_and_purpose_sensitive() -> None:
    manifest_id = uuid.uuid4()
    common = {
        "iso_week": "2026-W42",
        "policy_version": "weekly-v1",
        "input_manifest_id": manifest_id,
    }

    short = weekly_run_id(model_purpose="SHORT_5D", **common)

    assert short == weekly_run_id(model_purpose="SHORT_5D", **common)
    assert short != weekly_run_id(model_purpose="MEDIUM_20D", **common)


def test_create_run_uses_database_idempotency_key() -> None:
    connection = MagicMock()
    repository = WeeklyTrainingRepository(connection)
    manifest_id = uuid.uuid4()

    run_id = repository.create_run(
        iso_week="2026-W42",
        anchor_session=date(2026, 10, 16),
        model_purpose="SHORT_5D",
        policy_version="weekly-v1",
        input_manifest_id=manifest_id,
        training_cutoff=datetime(2026, 10, 16, 21, tzinfo=UTC),
        label_maturity_cutoff=date(2026, 10, 9),
    )

    assert run_id == weekly_run_id(
        iso_week="2026-W42",
        model_purpose="SHORT_5D",
        policy_version="weekly-v1",
        input_manifest_id=manifest_id,
    )
    query = connection.execute.call_args.args[0]
    assert "ON CONFLICT (iso_week, model_purpose, policy_version, input_manifest_id)" in query


def test_initial_activation_advances_generation_zero_to_one() -> None:
    connection = MagicMock()
    locked_assignment = MagicMock()
    locked_assignment.fetchone.return_value = None
    changed_assignment = MagicMock()
    changed_assignment.fetchone.return_value = {"generation": 1}
    connection.execute.side_effect = [locked_assignment, changed_assignment, MagicMock()]
    repository = WeeklyTrainingRepository(connection)

    assignment = repository.activate(
        model_purpose="SHORT_5D",
        model_version_id=uuid.uuid4(),
        artifact_uri="https://account.blob.core.windows.net/models/manifest.json",
        artifact_hash="a" * 64,
        blob_etag='"etag"',
        blob_version_id=None,
        weekly_run_id=uuid.uuid4(),
        expected_generation=0,
    )

    assert assignment.generation == 1
    assert "FOR UPDATE" in connection.execute.call_args_list[0].args[0]
    assignment_params = connection.execute.call_args_list[1].args[1]
    assert assignment_params[6] == 1
    assert assignment_params[-1] == 0


def test_initial_activation_detects_concurrent_insert() -> None:
    connection = MagicMock()
    locked_assignment = MagicMock()
    locked_assignment.fetchone.return_value = None
    lost_upsert = MagicMock()
    lost_upsert.fetchone.return_value = None
    connection.execute.side_effect = [locked_assignment, lost_upsert]
    repository = WeeklyTrainingRepository(connection)

    with pytest.raises(AssignmentGenerationConflict, match="changed concurrently"):
        repository.activate(
            model_purpose="SHORT_5D",
            model_version_id=uuid.uuid4(),
            artifact_uri="https://account.blob.core.windows.net/models/manifest.json",
            artifact_hash="e" * 64,
            blob_etag='"etag"',
            blob_version_id=None,
            weekly_run_id=uuid.uuid4(),
            expected_generation=0,
        )

    assert connection.execute.call_count == 2


def test_activation_rejects_stale_generation_before_writing() -> None:
    connection = MagicMock()
    connection.execute.return_value.fetchone.return_value = {
        "model_purpose": "SHORT_5D",
        "model_version_id": uuid.uuid4(),
        "artifact_uri": "https://account.blob.core.windows.net/models/old.json",
        "artifact_hash": "b" * 64,
        "blob_etag": '"old"',
        "blob_version_id": None,
        "generation": 3,
        "weekly_run_id": uuid.uuid4(),
        "activated_at": None,
    }
    repository = WeeklyTrainingRepository(connection)

    with pytest.raises(AssignmentGenerationConflict, match="Expected generation 2, found 3"):
        repository.activate(
            model_purpose="SHORT_5D",
            model_version_id=uuid.uuid4(),
            artifact_uri="https://account.blob.core.windows.net/models/new.json",
            artifact_hash="c" * 64,
            blob_etag='"new"',
            blob_version_id=None,
            weekly_run_id=uuid.uuid4(),
            expected_generation=2,
        )

    assert connection.execute.call_count == 1


def test_activation_requires_immutable_blob_identity() -> None:
    repository = WeeklyTrainingRepository(MagicMock())

    with pytest.raises(ValueError, match="ETag or version ID"):
        repository.activate(
            model_purpose="MEDIUM_20D",
            model_version_id=uuid.uuid4(),
            artifact_uri="https://account.blob.core.windows.net/models/manifest.json",
            artifact_hash="d" * 64,
            blob_etag=None,
            blob_version_id=None,
            weekly_run_id=uuid.uuid4(),
            expected_generation=0,
        )


def test_first_activation_rollback_removes_failed_pointer() -> None:
    connection = MagicMock()
    current = MagicMock()
    current.fetchone.return_value = {
        "model_purpose": "SHORT_5D",
        "model_version_id": uuid.uuid4(),
        "artifact_uri": "https://account.blob.core.windows.net/models/manifest.json",
        "artifact_hash": "d" * 64,
        "blob_etag": '"etag"',
        "blob_version_id": None,
        "generation": 1,
        "weekly_run_id": uuid.uuid4(),
        "activated_at": None,
    }
    no_history = MagicMock()
    no_history.fetchone.return_value = None
    deleted = MagicMock()
    deleted.fetchone.return_value = {"model_purpose": "SHORT_5D"}
    connection.execute.side_effect = [current, no_history, deleted]
    repository = WeeklyTrainingRepository(connection)

    result = repository.rollback(
        model_purpose="SHORT_5D",
        weekly_run_id=uuid.uuid4(),
        expected_generation=1,
    )

    assert result is None
    assert "DELETE FROM analytics.active_model_assignment" in (
        connection.execute.call_args_list[2].args[0]
    )


def test_transition_run_is_compare_and_set() -> None:
    connection = MagicMock()
    changed = MagicMock()
    changed.fetchone.return_value = {"weekly_run_id": uuid.uuid4()}
    connection.execute.return_value = changed
    repository = WeeklyTrainingRepository(connection)
    run_id = uuid.uuid4()

    repository.transition_run(
        weekly_run_id=run_id,
        expected_status="PENDING",
        next_status="RUNNING",
    )

    query, params = connection.execute.call_args.args
    assert "AND status = %s" in query
    assert params[-2:] == (run_id, "PENDING")


def test_failed_run_can_be_reset_for_retry() -> None:
    connection = MagicMock()
    changed = MagicMock()
    changed.fetchone.return_value = {"weekly_run_id": uuid.uuid4()}
    connection.execute.return_value = changed
    repository = WeeklyTrainingRepository(connection)

    repository.transition_run(
        weekly_run_id=uuid.uuid4(),
        expected_status="FAILED",
        next_status="PENDING",
    )

    query, params = connection.execute.call_args.args
    assert "WHEN %s = 'PENDING' THEN NULL" in query
    assert params[3:7] == ("PENDING",) * 4


def test_transition_run_rejects_stale_status() -> None:
    connection = MagicMock()
    unchanged = MagicMock()
    unchanged.fetchone.return_value = None
    connection.execute.return_value = unchanged
    repository = WeeklyTrainingRepository(connection)

    with pytest.raises(WeeklyRunStateConflict, match="expected status EVALUATED"):
        repository.transition_run(
            weekly_run_id=uuid.uuid4(),
            expected_status="EVALUATED",
            next_status="PROMOTED",
        )


def test_transition_run_rejects_skipped_lifecycle_stage() -> None:
    connection = MagicMock()
    repository = WeeklyTrainingRepository(connection)

    with pytest.raises(ValueError, match="PENDING -> PROMOTED"):
        repository.transition_run(
            weekly_run_id=uuid.uuid4(),
            expected_status="PENDING",
            next_status="PROMOTED",
        )

    connection.execute.assert_not_called()


def test_job_execution_name_cannot_be_rebound() -> None:
    connection = MagicMock()
    unchanged = MagicMock()
    unchanged.fetchone.return_value = None
    connection.execute.return_value = unchanged
    repository = WeeklyTrainingRepository(connection)

    with pytest.raises(WeeklyRunStateConflict, match="job execution name"):
        repository.set_job_execution_name(
            weekly_run_id=uuid.uuid4(),
            execution_name="candidate-weekly-2026-W42-SHORT_5D",
        )

    query = connection.execute.call_args.args[0]
    assert "container_job_execution_name IS NULL" in query