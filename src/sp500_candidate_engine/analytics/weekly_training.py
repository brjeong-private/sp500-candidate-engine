from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime

from sp500_candidate_engine.database import _canonical_hash, _stable_uuid

MODEL_PURPOSES = frozenset({"SHORT_5D", "MEDIUM_20D"})
RUN_TRANSITIONS = frozenset(
    {
        ("PENDING", "RUNNING"),
        ("PENDING", "FAILED"),
        ("FAILED", "PENDING"),
        ("RUNNING", "EVALUATED"),
        ("RUNNING", "FAILED"),
        ("EVALUATED", "PROMOTED"),
        ("EVALUATED", "REJECTED"),
        ("EVALUATED", "FAILED"),
        ("PROMOTED", "ROLLED_BACK"),
    }
)


class AssignmentGenerationConflict(RuntimeError):
    pass


class WeeklyRunStateConflict(RuntimeError):
    pass


@dataclass(frozen=True)
class WeeklyTrainingRun:
    weekly_run_id: uuid.UUID
    iso_week: str
    anchor_session: date
    model_purpose: str
    policy_version: str
    input_manifest_id: uuid.UUID
    training_cutoff: datetime
    label_maturity_cutoff: date
    status: str
    container_job_execution_name: str | None = None
    export_run_id: uuid.UUID | None = None
    challenger_model_version_id: uuid.UUID | None = None
    champion_model_version_id: uuid.UUID | None = None
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class ActiveModelAssignment:
    model_purpose: str
    model_version_id: uuid.UUID
    artifact_uri: str
    artifact_hash: str
    blob_etag: str | None
    blob_version_id: str | None
    generation: int
    weekly_run_id: uuid.UUID
    activated_at: datetime | None = None


def weekly_run_id(
    *,
    iso_week: str,
    model_purpose: str,
    policy_version: str,
    input_manifest_id: uuid.UUID,
) -> uuid.UUID:
    _validate_model_purpose(model_purpose)
    key = _canonical_hash(
        {
            "iso_week": iso_week,
            "model_purpose": model_purpose,
            "policy_version": policy_version,
            "input_manifest_id": input_manifest_id,
        }
    )
    return _stable_uuid("weekly-training-run", key)


def _validate_model_purpose(model_purpose: str) -> None:
    if model_purpose not in MODEL_PURPOSES:
        raise ValueError(f"Unsupported model purpose: {model_purpose}")


def _assignment_from_row(row: dict[str, object] | None) -> ActiveModelAssignment | None:
    if row is None:
        return None
    return ActiveModelAssignment(
        model_purpose=str(row["model_purpose"]),
        model_version_id=uuid.UUID(str(row["model_version_id"])),
        artifact_uri=str(row["artifact_uri"]),
        artifact_hash=str(row["artifact_hash"]),
        blob_etag=str(row["blob_etag"]) if row["blob_etag"] is not None else None,
        blob_version_id=(
            str(row["blob_version_id"]) if row["blob_version_id"] is not None else None
        ),
        generation=int(str(row["generation"])),
        weekly_run_id=uuid.UUID(str(row["weekly_run_id"])),
        activated_at=(
            row.get("activated_at")
            if isinstance(row.get("activated_at"), datetime)
            else None
        ),
    )


def _run_from_row(row: dict[str, object] | None) -> WeeklyTrainingRun | None:
    if row is None:
        return None
    return WeeklyTrainingRun(
        weekly_run_id=uuid.UUID(str(row["weekly_run_id"])),
        iso_week=str(row["iso_week"]),
        anchor_session=row["anchor_session"],  # type: ignore[arg-type]
        model_purpose=str(row["model_purpose"]),
        policy_version=str(row["policy_version"]),
        input_manifest_id=uuid.UUID(str(row["input_manifest_id"])),
        training_cutoff=row["training_cutoff"],  # type: ignore[arg-type]
        label_maturity_cutoff=row["label_maturity_cutoff"],  # type: ignore[arg-type]
        status=str(row["status"]),
        container_job_execution_name=(
            str(row["container_job_execution_name"])
            if row["container_job_execution_name"] is not None
            else None
        ),
        export_run_id=(
            uuid.UUID(str(row["export_run_id"])) if row["export_run_id"] is not None else None
        ),
        challenger_model_version_id=(
            uuid.UUID(str(row["challenger_model_version_id"]))
            if row["challenger_model_version_id"] is not None
            else None
        ),
        champion_model_version_id=(
            uuid.UUID(str(row["champion_model_version_id"]))
            if row["champion_model_version_id"] is not None
            else None
        ),
        error_code=str(row["error_code"]) if row["error_code"] is not None else None,
        error_message=str(row["error_message"]) if row["error_message"] is not None else None,
    )


class WeeklyTrainingRepository:
    def __init__(self, connection: object) -> None:
        self.connection = connection

    def create_run(
        self,
        *,
        iso_week: str,
        anchor_session: date,
        model_purpose: str,
        policy_version: str,
        input_manifest_id: uuid.UUID,
        training_cutoff: datetime,
        label_maturity_cutoff: date,
    ) -> uuid.UUID:
        run_id = weekly_run_id(
            iso_week=iso_week,
            model_purpose=model_purpose,
            policy_version=policy_version,
            input_manifest_id=input_manifest_id,
        )
        self.connection.execute(  # type: ignore[attr-defined]
            """
            INSERT INTO analytics.weekly_training_run(
                weekly_run_id, iso_week, anchor_session, model_purpose,
                policy_version, input_manifest_id, training_cutoff,
                label_maturity_cutoff, status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'PENDING')
            ON CONFLICT (iso_week, model_purpose, policy_version, input_manifest_id)
            DO NOTHING
            """,
            (
                run_id,
                iso_week,
                anchor_session,
                model_purpose,
                policy_version,
                input_manifest_id,
                training_cutoff,
                label_maturity_cutoff,
            ),
        )
        return run_id

    def get_run(self, *, weekly_run_id: uuid.UUID) -> WeeklyTrainingRun | None:
        row = self.connection.execute(  # type: ignore[attr-defined]
            """
            SELECT weekly_run_id, iso_week, anchor_session, model_purpose,
                   policy_version, input_manifest_id, training_cutoff,
                   label_maturity_cutoff, status, container_job_execution_name,
                   export_run_id, challenger_model_version_id,
                   champion_model_version_id, error_code, error_message
              FROM analytics.weekly_training_run
             WHERE weekly_run_id = %s
            """,
            (weekly_run_id,),
        ).fetchone()
        return _run_from_row(row)

    def set_job_execution_name(
        self, *, weekly_run_id: uuid.UUID, execution_name: str
    ) -> None:
        row = self.connection.execute(  # type: ignore[attr-defined]
            """
            UPDATE analytics.weekly_training_run
               SET container_job_execution_name = %s,
                   updated_at = now()
             WHERE weekly_run_id = %s
               AND status IN ('PENDING', 'RUNNING')
               AND (
                   container_job_execution_name IS NULL
                   OR container_job_execution_name = %s
               )
            RETURNING weekly_run_id
            """,
            (execution_name, weekly_run_id, execution_name),
        ).fetchone()
        if row is None:
            raise WeeklyRunStateConflict("Weekly run cannot accept this job execution name")

    def transition_run(
        self,
        *,
        weekly_run_id: uuid.UUID,
        expected_status: str,
        next_status: str,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        if (expected_status, next_status) not in RUN_TRANSITIONS:
            raise ValueError(
                f"Unsupported weekly run transition: {expected_status} -> {next_status}"
            )
        if (error_code is None) != (error_message is None):
            raise ValueError("error_code and error_message must be supplied together")
        row = self.connection.execute(  # type: ignore[attr-defined]
            """
            UPDATE analytics.weekly_training_run
               SET status = %s,
                   error_code = %s,
                   error_message = %s,
                   started_at = CASE
                       WHEN %s = 'PENDING' THEN NULL
                       WHEN %s = 'RUNNING' THEN COALESCE(started_at, now())
                       ELSE started_at
                   END,
                   finished_at = CASE
                       WHEN %s = 'PENDING' THEN NULL
                       WHEN %s IN ('PROMOTED', 'REJECTED', 'ROLLED_BACK', 'FAILED')
                           THEN now()
                       ELSE finished_at
                   END,
                   updated_at = now()
             WHERE weekly_run_id = %s
               AND status = %s
            RETURNING weekly_run_id
            """,
            (
                next_status,
                error_code,
                error_message,
                next_status,
                next_status,
                next_status,
                next_status,
                weekly_run_id,
                expected_status,
            ),
        ).fetchone()
        if row is None:
            raise WeeklyRunStateConflict(
                f"Weekly run is no longer in expected status {expected_status}"
            )

    def get_active_assignment(
        self, *, model_purpose: str, for_update: bool = False
    ) -> ActiveModelAssignment | None:
        _validate_model_purpose(model_purpose)
        query = """
            SELECT model_purpose, model_version_id, artifact_uri, artifact_hash,
                   blob_etag, blob_version_id, generation, weekly_run_id, activated_at
              FROM analytics.active_model_assignment
             WHERE model_purpose = %s
        """
        if for_update:
            query += " FOR UPDATE"
        row = self.connection.execute(  # type: ignore[attr-defined]
            query, (model_purpose,)
        ).fetchone()
        return _assignment_from_row(row)

    def activate(
        self,
        *,
        model_purpose: str,
        model_version_id: uuid.UUID,
        artifact_uri: str,
        artifact_hash: str,
        blob_etag: str | None,
        blob_version_id: str | None,
        weekly_run_id: uuid.UUID,
        expected_generation: int,
        action: str = "ACTIVATE",
    ) -> ActiveModelAssignment:
        _validate_model_purpose(model_purpose)
        if action not in {"ACTIVATE", "ROLLBACK"}:
            raise ValueError(f"Unsupported assignment action: {action}")
        if blob_etag is None and blob_version_id is None:
            raise ValueError("Blob ETag or version ID is required")

        current = self.get_active_assignment(model_purpose=model_purpose, for_update=True)
        actual_generation = current.generation if current is not None else 0
        if actual_generation != expected_generation:
            raise AssignmentGenerationConflict(
                f"Expected generation {expected_generation}, found {actual_generation}"
            )
        next_generation = actual_generation + 1
        history_id = uuid.uuid4()
        replaced_model_version_id = current.model_version_id if current is not None else None

        changed_row = self.connection.execute(  # type: ignore[attr-defined]
            """
            INSERT INTO analytics.active_model_assignment(
                model_purpose, model_version_id, artifact_uri, artifact_hash,
                blob_etag, blob_version_id, generation, weekly_run_id, activated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (model_purpose) DO UPDATE SET
                model_version_id = EXCLUDED.model_version_id,
                artifact_uri = EXCLUDED.artifact_uri,
                artifact_hash = EXCLUDED.artifact_hash,
                blob_etag = EXCLUDED.blob_etag,
                blob_version_id = EXCLUDED.blob_version_id,
                generation = EXCLUDED.generation,
                weekly_run_id = EXCLUDED.weekly_run_id,
                activated_at = EXCLUDED.activated_at
            WHERE analytics.active_model_assignment.generation = %s
            RETURNING generation
            """,
            (
                model_purpose,
                model_version_id,
                artifact_uri,
                artifact_hash,
                blob_etag,
                blob_version_id,
                next_generation,
                weekly_run_id,
                expected_generation,
            ),
        ).fetchone()
        if changed_row is None:
            raise AssignmentGenerationConflict(
                f"Assignment changed concurrently from generation {expected_generation}"
            )
        self.connection.execute(  # type: ignore[attr-defined]
            """
            INSERT INTO analytics.active_model_assignment_history(
                assignment_history_id, model_purpose, model_version_id,
                artifact_uri, artifact_hash, blob_etag, blob_version_id,
                generation, weekly_run_id, action, replaced_model_version_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                history_id,
                model_purpose,
                model_version_id,
                artifact_uri,
                artifact_hash,
                blob_etag,
                blob_version_id,
                next_generation,
                weekly_run_id,
                action,
                replaced_model_version_id,
            ),
        )
        return ActiveModelAssignment(
            model_purpose=model_purpose,
            model_version_id=model_version_id,
            artifact_uri=artifact_uri,
            artifact_hash=artifact_hash,
            blob_etag=blob_etag,
            blob_version_id=blob_version_id,
            generation=next_generation,
            weekly_run_id=weekly_run_id,
        )

    def rollback(
        self,
        *,
        model_purpose: str,
        weekly_run_id: uuid.UUID,
        expected_generation: int,
    ) -> ActiveModelAssignment | None:
        _validate_model_purpose(model_purpose)
        current = self.get_active_assignment(model_purpose=model_purpose, for_update=True)
        if current is None or current.generation != expected_generation:
            actual = current.generation if current is not None else 0
            raise AssignmentGenerationConflict(
                f"Expected generation {expected_generation}, found {actual}"
            )
        previous = self.connection.execute(  # type: ignore[attr-defined]
            """
            SELECT model_version_id, artifact_uri, artifact_hash,
                   blob_etag, blob_version_id
              FROM analytics.active_model_assignment_history
             WHERE model_purpose = %s
               AND generation < %s
             ORDER BY generation DESC
             LIMIT 1
            """,
            (model_purpose, expected_generation),
        ).fetchone()
        if previous is None:
            deleted = self.connection.execute(  # type: ignore[attr-defined]
                """
                DELETE FROM analytics.active_model_assignment
                 WHERE model_purpose = %s
                   AND generation = %s
                RETURNING model_purpose
                """,
                (model_purpose, expected_generation),
            ).fetchone()
            if deleted is None:
                raise AssignmentGenerationConflict(
                    f"Assignment changed concurrently from generation {expected_generation}"
                )
            return None
        return self.activate(
            model_purpose=model_purpose,
            model_version_id=uuid.UUID(str(previous["model_version_id"])),
            artifact_uri=str(previous["artifact_uri"]),
            artifact_hash=str(previous["artifact_hash"]),
            blob_etag=(
                str(previous["blob_etag"])
                if previous["blob_etag"] is not None
                else None
            ),
            blob_version_id=(
                str(previous["blob_version_id"])
                if previous["blob_version_id"] is not None
                else None
            ),
            weekly_run_id=weekly_run_id,
            expected_generation=expected_generation,
            action="ROLLBACK",
        )