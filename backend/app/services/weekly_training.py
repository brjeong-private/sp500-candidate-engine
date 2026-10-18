from __future__ import annotations

import os
import re
import uuid
from collections.abc import Callable
from pathlib import Path

from backend.app.schemas.weekly_training import (
    ActivationSmokeResult,
    WeeklyEligibility,
    WeeklyTrainingAccepted,
    WeeklyTrainingStatus,
)
from backend.app.services.model_artifacts import (
    ArtifactBinding,
    ModelArtifactLoadError,
    load_model_artifact,
)
from sp500_candidate_engine.analytics.promotion import (
    DEFAULT_WEEKLY_POLICY_VERSION,
    load_weekly_retraining_policy,
    weekly_retraining_policy_path,
)
from sp500_candidate_engine.analytics.weekly_training import (
    WeeklyTrainingRepository,
    WeeklyTrainingRun,
)
from sp500_candidate_engine.database import Database

IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
DEFAULT_POLICY_VERSION = DEFAULT_WEEKLY_POLICY_VERSION


class WeeklyTrainingConflict(RuntimeError):
    pass


class WeeklyTrainingNotFound(LookupError):
    pass


class WeeklyTrainingNotEligible(RuntimeError):
    pass


def _iso_week(value) -> str:
    iso = value.isocalendar()
    return f"{iso.year:04d}-W{iso.week:02d}"


def _status(run: WeeklyTrainingRun) -> WeeklyTrainingStatus:
    return WeeklyTrainingStatus(
        weekly_run_id=run.weekly_run_id,
        iso_week=run.iso_week,
        anchor_session=run.anchor_session,
        model_purpose=run.model_purpose,  # type: ignore[arg-type]
        policy_version=run.policy_version,
        input_manifest_id=run.input_manifest_id,
        training_cutoff=run.training_cutoff,
        label_maturity_cutoff=run.label_maturity_cutoff,
        status=run.status,  # type: ignore[arg-type]
        container_job_execution_name=run.container_job_execution_name,
        export_run_id=run.export_run_id,
        challenger_model_version_id=run.challenger_model_version_id,
        champion_model_version_id=run.champion_model_version_id,
        error_code=run.error_code,
    )


class WeeklyTrainingService:
    """Own weekly acceptance in PostgreSQL and expose only allowlisted state."""

    def __init__(
        self,
        database: Database,
        *,
        policy_version: str = DEFAULT_POLICY_VERSION,
        smoke_runner: Callable[[WeeklyTrainingRun], bool] | None = None,
    ) -> None:
        self.database = database
        self.policy_version = policy_version
        self.policy = load_weekly_retraining_policy(weekly_retraining_policy_path(
            Path(__file__).resolve().parents[3] / "config" / "analytics", policy_version,
        ))
        if self.policy.version != policy_version:
            raise ValueError("Weekly policy version does not match configuration")
        self.smoke_runner = smoke_runner

    def eligibility(self, *, model_purpose: str | None = None) -> WeeklyEligibility:
        with self.database.connect() as connection, connection.transaction():
            row = connection.execute(
                """
                SELECT max(ir.target_date) AS anchor_session,
                       ec.input_manifest_id,
                       ec.cutoff_at AS training_cutoff
                  FROM ops.execution_context ec
                  JOIN ops.input_manifest_member imm
                    ON imm.input_manifest_id = ec.input_manifest_id
                  JOIN ops.source_snapshot ss
                    ON ss.source_snapshot_id = imm.source_snapshot_id
                  JOIN ops.ingestion_run ir
                    ON ir.ingestion_run_id = ss.ingestion_run_id
                  WHERE ec.knowledge_mode = 'OPERATIONAL_REPLAY'
                    AND ir.status = 'SUCCEEDED'
                   AND NOT EXISTS (
                       SELECT 1
                         FROM ops.data_quality_issue dqi
                        WHERE dqi.ingestion_run_id = ir.ingestion_run_id
                          AND dqi.severity = 'BLOCKING'
                   )
                 GROUP BY ec.execution_context_id, ec.input_manifest_id, ec.cutoff_at
                 HAVING bool_and(ir.status = 'SUCCEEDED')
                 ORDER BY max(ir.target_date) DESC, ec.cutoff_at DESC
                 LIMIT 1
                """
            ).fetchone()
            if row is None:
                return WeeklyEligibility(eligible=False, reason="NO_COMPLETE_MANIFEST")
            iso_week = _iso_week(row["anchor_session"])
            if model_purpose is not None:
                existing = connection.execute(
                    """
                    SELECT 1
                      FROM analytics.weekly_training_run
                     WHERE iso_week = %s
                       AND model_purpose = %s
                       AND policy_version = %s
                       AND input_manifest_id = %s
                     LIMIT 1
                    """,
                    (
                        iso_week,
                        model_purpose,
                        self.policy_version,
                        row["input_manifest_id"],
                    ),
                ).fetchone()
                if existing is not None:
                    return WeeklyEligibility(
                        eligible=False,
                        iso_week=iso_week,
                        anchor_session=row["anchor_session"],
                        input_manifest_id=row["input_manifest_id"],
                        training_cutoff=row["training_cutoff"],
                        label_maturity_cutoff=row["anchor_session"],
                        reason="ALREADY_ACCEPTED",
                    )
            return WeeklyEligibility(
                eligible=True,
                iso_week=iso_week,
                anchor_session=row["anchor_session"],
                input_manifest_id=row["input_manifest_id"],
                training_cutoff=row["training_cutoff"],
                label_maturity_cutoff=row["anchor_session"],
                reason="READY",
            )

    def accept(self, *, model_purpose: str, idempotency_key: str) -> WeeklyTrainingAccepted:
        if model_purpose not in self.policy.purposes:
            raise ValueError("Model purpose is not enabled by the weekly training policy")
        if IDEMPOTENCY_KEY_PATTERN.fullmatch(idempotency_key) is None:
            raise ValueError("Invalid Idempotency-Key")
        eligibility = self.eligibility()
        if not eligibility.eligible:
            raise WeeklyTrainingNotEligible("Weekly training inputs are not ready")
        assert eligibility.iso_week is not None
        assert eligibility.anchor_session is not None
        assert eligibility.input_manifest_id is not None
        assert eligibility.training_cutoff is not None
        assert eligibility.label_maturity_cutoff is not None
        with self.database.connect() as connection, connection.transaction():
            repository = WeeklyTrainingRepository(connection)
            run_id = repository.create_run(
                iso_week=eligibility.iso_week,
                anchor_session=eligibility.anchor_session,
                model_purpose=model_purpose,
                policy_version=self.policy_version,
                input_manifest_id=eligibility.input_manifest_id,
                training_cutoff=eligibility.training_cutoff,
                label_maturity_cutoff=eligibility.label_maturity_cutoff,
            )
            run = repository.get_run(weekly_run_id=run_id)
            if run is None:
                raise RuntimeError("Accepted weekly run was not persisted")
            if run.status == "FAILED":
                repository.transition_run(
                    weekly_run_id=run.weekly_run_id,
                    expected_status="FAILED",
                    next_status="PENDING",
                )
                run = repository.get_run(weekly_run_id=run.weekly_run_id)
                if run is None:
                    raise RuntimeError("Retried weekly run was not persisted")
        return WeeklyTrainingAccepted(
            weekly_run_id=run.weekly_run_id,
            model_purpose=run.model_purpose,  # type: ignore[arg-type]
            status=run.status,  # type: ignore[arg-type]
            status_url=f"/api/v1/pipeline-runs/weekly/{run.weekly_run_id}",
        )

    def get(self, weekly_run_id: uuid.UUID) -> WeeklyTrainingStatus:
        with self.database.connect() as connection:
            run = WeeklyTrainingRepository(connection).get_run(weekly_run_id=weekly_run_id)
        if run is None:
            raise WeeklyTrainingNotFound("Weekly training run not found")
        return _status(run)

    def bind_execution(
        self,
        weekly_run_id: uuid.UUID,
        *,
        execution_name: str,
    ) -> WeeklyTrainingStatus:
        if (
            not execution_name
            or len(execution_name) > 128
            or re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", execution_name) is None
        ):
            raise ValueError("Invalid Container Apps Job execution name")
        with self.database.connect() as connection, connection.transaction():
            repository = WeeklyTrainingRepository(connection)
            if repository.get_run(weekly_run_id=weekly_run_id) is None:
                raise WeeklyTrainingNotFound("Weekly training run not found")
            repository.set_job_execution_name(
                weekly_run_id=weekly_run_id,
                execution_name=execution_name,
            )
            run = repository.get_run(weekly_run_id=weekly_run_id)
        if run is None:
            raise WeeklyTrainingNotFound("Weekly training run not found")
        return _status(run)

    def activation_smoke(self, weekly_run_id: uuid.UUID) -> ActivationSmokeResult:
        with self.database.connect() as connection:
            repository = WeeklyTrainingRepository(connection)
            run = repository.get_run(weekly_run_id=weekly_run_id)
            if run is None:
                raise WeeklyTrainingNotFound("Weekly training run not found")
            if run.status != "PROMOTED":
                raise WeeklyTrainingConflict("Activation smoke requires a promoted weekly run")
            assignment = repository.get_active_assignment(model_purpose=run.model_purpose)
            if assignment is None or assignment.weekly_run_id != run.weekly_run_id:
                raise WeeklyTrainingConflict("Promoted run is not the active assignment")
        try:
            if self.smoke_runner is not None:
                passed = bool(self.smoke_runner(run))
            else:
                load_model_artifact(
                    binding=ArtifactBinding(
                        model_purpose=assignment.model_purpose,
                        artifact_uri=assignment.artifact_uri,
                        artifact_hash=assignment.artifact_hash,
                        blob_etag=assignment.blob_etag,
                        blob_version_id=assignment.blob_version_id,
                    ),
                    cache_directory=Path(
                        os.environ.get(
                            "MODEL_ARTIFACT_CACHE_DIR",
                            "/tmp/candidate-model-cache",
                        )
                    ),
                )
                passed = True
        except (ModelArtifactLoadError, OSError):
            passed = False
        if not passed:
            with self.database.connect() as connection, connection.transaction():
                repository = WeeklyTrainingRepository(connection)
                current = repository.get_active_assignment(
                    model_purpose=run.model_purpose,
                    for_update=True,
                )
                if current is None or current.weekly_run_id != run.weekly_run_id:
                    raise WeeklyTrainingConflict(
                        "Active assignment changed before smoke rollback"
                    )
                previous = repository.rollback(
                    model_purpose=run.model_purpose,
                    weekly_run_id=run.weekly_run_id,
                    expected_generation=current.generation,
                )
                connection.execute(
                    """
                    UPDATE analytics.model_version
                       SET promotion_status = 'REJECTED'
                     WHERE model_version_id = %s
                       AND promotion_status = 'CHAMPION'
                    """,
                    (run.champion_model_version_id,),
                )
                if previous is not None:
                    connection.execute(
                        """
                        UPDATE analytics.model_version
                           SET promotion_status = 'CHAMPION'
                         WHERE model_version_id = %s
                           AND promotion_status = 'ARCHIVED'
                        """,
                        (previous.model_version_id,),
                    )
                repository.transition_run(
                    weekly_run_id=run.weekly_run_id,
                    expected_status="PROMOTED",
                    next_status="ROLLED_BACK",
                    error_code="ACTIVATION_SMOKE_FAILED",
                    error_message="Candidate activation smoke failed",
                )
        return ActivationSmokeResult(
            weekly_run_id=run.weekly_run_id,
            model_purpose=run.model_purpose,  # type: ignore[arg-type]
            passed=bool(passed),
        )
