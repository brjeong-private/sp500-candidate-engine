from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import timedelta
from email.utils import formatdate
from importlib.metadata import version
from pathlib import Path
from urllib.parse import quote

import httpx
from azure.identity import DefaultAzureCredential

from sp500_candidate_engine.analytics.artifacts import (
    PackagedArtifact,
    package_model_artifact,
)
from sp500_candidate_engine.analytics.config import load_versioned_config
from sp500_candidate_engine.analytics.historical_export import (
    HistoricalQlibExportService,
)
from sp500_candidate_engine.analytics.phase45_workflow import (
    TrainingWorkflowSummary,
    run_training_only_workflow,
)
from sp500_candidate_engine.analytics.promotion import (
    PromotionEvaluation,
    evaluate_promotion,
    load_weekly_retraining_policy,
)
from sp500_candidate_engine.analytics.weekly_training import (
    WeeklyRunStateConflict,
    WeeklyTrainingRepository,
    WeeklyTrainingRun,
)
from sp500_candidate_engine.config import Settings
from sp500_candidate_engine.database import Database

CONFIGS = {
    "SHORT_5D": ("model_lightgbm_v2.yaml", "label_forward_return_5d_v2.yaml"),
    "MEDIUM_20D": ("model_lightgbm_20d_v1.yaml", "label_forward_return_20d_v1.yaml"),
}
TRAINING_HISTORY_DAYS = 730
AZURE_STORAGE_SCOPE = "https://storage.azure.com/.default"
AZURE_STORAGE_API_VERSION = "2023-11-03"


@dataclass(frozen=True)
class UploadedArtifact:
    manifest_uri: str
    manifest_etag: str | None
    manifest_version_id: str | None


def _put_immutable_blob(
    client: httpx.Client,
    *,
    uri: str,
    content: bytes,
    token: str,
    content_type: str,
) -> httpx.Response:
    headers = {
        "Authorization": f"Bearer {token}",
        "x-ms-date": formatdate(usegmt=True),
        "x-ms-version": AZURE_STORAGE_API_VERSION,
        "x-ms-blob-type": "BlockBlob",
        "If-None-Match": "*",
        "Content-Type": content_type,
    }
    response = client.put(uri, headers=headers, content=content)
    if response.status_code in {409, 412}:
        existing = client.get(
            uri,
            headers={
                "Authorization": f"Bearer {token}",
                "x-ms-date": formatdate(usegmt=True),
                "x-ms-version": AZURE_STORAGE_API_VERSION,
            },
        )
        existing.raise_for_status()
        if existing.content != content:
            raise RuntimeError("Immutable model artifact already exists with different content")
        return existing
    response.raise_for_status()
    return response


def _upload_model_artifact(packaged: PackagedArtifact) -> UploadedArtifact:
    endpoint = os.environ.get("CANDIDATE_ARTIFACT_BLOB_ENDPOINT", "").strip().rstrip("/")
    container = os.environ.get("CANDIDATE_ARTIFACT_CONTAINER", "").strip()
    if not endpoint.startswith("https://") or not endpoint.endswith(".blob.core.windows.net"):
        raise ValueError("CANDIDATE_ARTIFACT_BLOB_ENDPOINT is invalid")
    if not container or "/" in container or "\\" in container:
        raise ValueError("CANDIDATE_ARTIFACT_CONTAINER is invalid")
    prefix = (
        f"{endpoint}/{quote(container, safe='')}/models/"
        f"{packaged.manifest.model_purpose.lower()}/"
        f"{packaged.manifest.model_version_id}"
    )
    credential = DefaultAzureCredential()
    token = credential.get_token(AZURE_STORAGE_SCOPE).token
    with httpx.Client(timeout=120) as client:
        _put_immutable_blob(
            client,
            uri=f"{prefix}/{packaged.manifest.model_file}",
            content=packaged.model_path.read_bytes(),
            token=token,
            content_type="application/octet-stream",
        )
        response = _put_immutable_blob(
            client,
            uri=f"{prefix}/manifest.json",
            content=packaged.manifest_path.read_bytes(),
            token=token,
            content_type="application/json",
        )
    return UploadedArtifact(
        manifest_uri=f"{prefix}/manifest.json",
        manifest_etag=response.headers.get("etag"),
        manifest_version_id=response.headers.get("x-ms-version-id"),
    )


def _prepare_training_export(
    database: Database,
    run: WeeklyTrainingRun,
) -> Path:
    work_root = Path(
        os.environ.get("TRAINING_WORK_ROOT", "/tmp/candidate-training")
    ).resolve()
    output_root = work_root / "qlib"
    summary = HistoricalQlibExportService(database).export(
        start_date=run.anchor_session - timedelta(days=TRAINING_HISTORY_DAYS),
        end_date=run.anchor_session,
        output_root=output_root,
        qlib_version=version("pyqlib"),
        decision_cutoff=run.training_cutoff,
        require_snapshot_available_by_cutoff=True,
    )
    return output_root / str(summary.export_run_id)


class WeeklyTrainingJob:
    """Container Job seam whose only external identifiers are run ID and purpose."""

    def __init__(
        self,
        database: Database,
        settings: Settings,
        *,
        repository_root: Path,
        trainer: Callable[..., TrainingWorkflowSummary] = run_training_only_workflow,
        export_preparer: Callable[[Database, WeeklyTrainingRun], Path] = (
            _prepare_training_export
        ),
    ) -> None:
        self.database = database
        self.settings = settings
        self.repository_root = repository_root.resolve()
        self.trainer = trainer
        self.export_preparer = export_preparer

    def _evaluate_and_finalize(
        self,
        *,
        run: WeeklyTrainingRun,
        summary: TrainingWorkflowSummary,
    ) -> PromotionEvaluation:
        challenger_metrics = summary.metrics[summary.selected_shadow_model]
        with self.database.connect() as connection:
            repository = WeeklyTrainingRepository(connection)
            incumbent = repository.get_active_assignment(
                model_purpose=run.model_purpose
            )
            incumbent_metrics = None
            if incumbent is not None:
                incumbent_row = connection.execute(
                    """
                    SELECT metrics
                      FROM analytics.model_version
                     WHERE model_version_id = %s
                    """,
                    (incumbent.model_version_id,),
                ).fetchone()
                if incumbent_row is None:
                    raise RuntimeError("Active incumbent model is missing")
                incumbent_metrics = incumbent_row["metrics"]
            challenger = connection.execute(
                """
                SELECT model_name, version, config_hash, artifact_hash,
                       processor_version_id, label_semantics, model_purpose,
                       return_policy
                  FROM analytics.model_version
                 WHERE model_version_id = %s
                """,
                (summary.model_version_id,),
            ).fetchone()
        if challenger is None:
            raise RuntimeError("Challenger model registration is missing")

        policy = load_weekly_retraining_policy(
            self.repository_root / "config" / "analytics" / "weekly_retraining_v1.yaml"
        )
        if policy.version != run.policy_version:
            raise RuntimeError("Weekly run policy version does not match configuration")
        evaluation = evaluate_promotion(
            policy=policy,
            model_purpose=run.model_purpose,
            challenger_metrics=challenger_metrics,
            incumbent_metrics=incumbent_metrics,
        )
        gate_results = {
            name: asdict(result) for name, result in evaluation.gate_results.items()
        }

        packaged = None
        uploaded = None
        if evaluation.promoted:
            artifact_root = Path(
                os.environ.get("TRAINING_WORK_ROOT", "/tmp/candidate-training")
            ) / "artifacts" / str(summary.model_version_id)
            packaged = package_model_artifact(
                source_directory=summary.experiment_dir,
                output_directory=artifact_root,
                model_version_id=summary.model_version_id,
                model_purpose=run.model_purpose,
                registered_model=challenger,
                config_root=self.repository_root / "config" / "analytics",
            )
            uploaded = _upload_model_artifact(packaged)

        with self.database.connect() as connection, connection.transaction():
            repository = WeeklyTrainingRepository(connection)
            current = repository.get_active_assignment(
                model_purpose=run.model_purpose,
                for_update=True,
            )
            connection.execute(
                """
                INSERT INTO analytics.model_promotion_decision(
                    promotion_decision_id, weekly_run_id,
                    incumbent_model_version_id, challenger_model_version_id,
                    policy_version, decision, gate_results
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (weekly_run_id) DO NOTHING
                """,
                (
                    uuid.uuid4(),
                    run.weekly_run_id,
                    current.model_version_id if current is not None else None,
                    summary.model_version_id,
                    run.policy_version,
                    evaluation.decision,
                    json.dumps(gate_results, sort_keys=True),
                ),
            )
            if not evaluation.promoted:
                connection.execute(
                    """
                    UPDATE analytics.model_version
                       SET promotion_status = 'REJECTED'
                     WHERE model_version_id = %s
                       AND promotion_status = 'SHADOW'
                    """,
                    (summary.model_version_id,),
                )
                repository.transition_run(
                    weekly_run_id=run.weekly_run_id,
                    expected_status="EVALUATED",
                    next_status="REJECTED",
                )
                return evaluation

            assert packaged is not None
            assert uploaded is not None
            if current is not None:
                connection.execute(
                    """
                    UPDATE analytics.model_version
                       SET promotion_status = 'ARCHIVED'
                     WHERE model_version_id = %s
                       AND promotion_status = 'CHAMPION'
                    """,
                    (current.model_version_id,),
                )
            changed = connection.execute(
                """
                UPDATE analytics.model_version
                   SET promotion_status = 'CHAMPION'
                 WHERE model_version_id = %s
                   AND promotion_status = 'SHADOW'
                RETURNING model_version_id
                """,
                (summary.model_version_id,),
            ).fetchone()
            if changed is None:
                raise RuntimeError("Challenger model is no longer promotable")
            repository.activate(
                model_purpose=run.model_purpose,
                model_version_id=summary.model_version_id,
                artifact_uri=uploaded.manifest_uri,
                artifact_hash=packaged.manifest_sha256,
                blob_etag=uploaded.manifest_etag,
                blob_version_id=uploaded.manifest_version_id,
                weekly_run_id=run.weekly_run_id,
                expected_generation=current.generation if current is not None else 0,
            )
            connection.execute(
                """
                UPDATE analytics.weekly_training_run
                   SET champion_model_version_id = %s,
                       updated_at = now()
                 WHERE weekly_run_id = %s
                   AND status = 'EVALUATED'
                """,
                (summary.model_version_id, run.weekly_run_id),
            )
            repository.transition_run(
                weekly_run_id=run.weekly_run_id,
                expected_status="EVALUATED",
                next_status="PROMOTED",
            )
        return evaluation

    def run(self, *, weekly_run_id: uuid.UUID, model_purpose: str) -> TrainingWorkflowSummary:
        if model_purpose not in CONFIGS:
            raise ValueError("model_purpose must be SHORT_5D or MEDIUM_20D")
        with self.database.connect() as connection, connection.transaction():
            repository = WeeklyTrainingRepository(connection)
            run = repository.get_run(weekly_run_id=weekly_run_id)
            if run is None:
                raise LookupError("Weekly training run not found")
            if run.model_purpose != model_purpose:
                raise ValueError("Weekly run model purpose mismatch")
            repository.transition_run(
                weekly_run_id=weekly_run_id,
                expected_status="PENDING",
                next_status="RUNNING",
            )

        model_filename, label_filename = CONFIGS[model_purpose]
        config_root = self.repository_root / "config" / "analytics"
        model_config = load_versioned_config(
            config_root / model_filename,
            required_keys=("seed", "prediction_semantics", "model", "walk_forward", "baselines"),
        )
        label_config = load_versioned_config(
            config_root / label_filename,
            required_keys=("horizon_sessions", "entry_rule", "exit_rule"),
        )
        try:
            export_dir = self.export_preparer(
                self.database,
                run,
            )
            summary = self.trainer(
                settings=self.settings,
                export_dir=export_dir,
                model_config=model_config,
                label_config=label_config,
                output_root=export_dir.parent.parent / "weekly",
            )
            with self.database.connect() as connection, connection.transaction():
                connection.execute(
                    """
                    UPDATE analytics.weekly_training_run
                       SET export_run_id = %s,
                           challenger_model_version_id = %s,
                           updated_at = now()
                     WHERE weekly_run_id = %s
                       AND status = 'RUNNING'
                    """,
                    (summary.export_run_id, summary.model_version_id, weekly_run_id),
                )
                WeeklyTrainingRepository(connection).transition_run(
                    weekly_run_id=weekly_run_id,
                    expected_status="RUNNING",
                    next_status="EVALUATED",
                )
            self._evaluate_and_finalize(run=run, summary=summary)
            return summary
        except Exception:
            with (
                self.database.connect() as connection,
                connection.transaction(),
                suppress(WeeklyRunStateConflict),
            ):
                repository = WeeklyTrainingRepository(connection)
                failed_run = repository.get_run(weekly_run_id=weekly_run_id)
                if failed_run is not None and failed_run.status in {"RUNNING", "EVALUATED"}:
                    repository.transition_run(
                        weekly_run_id=weekly_run_id,
                        expected_status=failed_run.status,
                        next_status="FAILED",
                        error_code="TRAINING_JOB_FAILED",
                        error_message="Weekly training job failed",
                    )
            raise


def run_weekly_training_job(
    *,
    database: Database,
    settings: Settings,
    repository_root: Path,
    weekly_run_id: uuid.UUID,
    model_purpose: str,
) -> TrainingWorkflowSummary:
    return WeeklyTrainingJob(
        database,
        settings,
        repository_root=repository_root,
    ).run(weekly_run_id=weekly_run_id, model_purpose=model_purpose)


def _required_job_input(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _repository_root() -> Path:
    working_root = Path.cwd().resolve()
    if (working_root / "config" / "analytics").is_dir():
        return working_root
    source_root = Path(__file__).resolve().parents[3]
    if (source_root / "config" / "analytics").is_dir():
        return source_root
    raise RuntimeError("Repository analytics configuration is unavailable")


def main() -> None:
    weekly_run_id = uuid.UUID(_required_job_input("WEEKLY_RUN_ID"))
    model_purpose = _required_job_input("MODEL_PURPOSE")
    settings = Settings.from_env()
    run_weekly_training_job(
        database=Database(settings),
        settings=settings,
        repository_root=_repository_root(),
        weekly_run_id=weekly_run_id,
        model_purpose=model_purpose,
    )


if __name__ == "__main__":
    main()
