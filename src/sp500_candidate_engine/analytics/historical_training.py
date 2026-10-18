"""Explicit, isolated historical challengers. This module has no activation path."""

from __future__ import annotations

import argparse
import json
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time, timedelta
from importlib.metadata import version
from pathlib import Path

import exchange_calendars

from sp500_candidate_engine import __version__
from sp500_candidate_engine.analytics.artifacts import (
    ArtifactManifest,
    PackagedArtifact,
    package_model_artifact,
    sha256_file,
)
from sp500_candidate_engine.analytics.certified_scope import DATASET_CODE, read_scope_artifact
from sp500_candidate_engine.analytics.config import load_versioned_config
from sp500_candidate_engine.analytics.historical_export import (
    HistoricalInputContext,
    HistoricalQlibExportService,
)
from sp500_candidate_engine.analytics.historical_safety import (
    HistoricalSafetyError,
    HistoricalTrainingFence,
)
from sp500_candidate_engine.analytics.phase45_workflow import (
    TrainingWorkflowSummary,
    run_training_only_workflow,
)
from sp500_candidate_engine.analytics.promotion import (
    DEFAULT_WEEKLY_POLICY_VERSION,
    evaluate_promotion,
    load_weekly_retraining_policy,
    weekly_retraining_policy_path,
)
from sp500_candidate_engine.analytics.source_repository import SourceRepository
from sp500_candidate_engine.config import Settings
from sp500_candidate_engine.database import Database, _canonical_hash, _stable_uuid
from sp500_candidate_engine.models import NEW_YORK

CONTRACT_VERSION = "historical-medium-20d-challenger-v1"
CODE_COMPONENTS = (
    "historical_training.py", "historical_training_context.py", "historical_safety.py",
    "phase45_workflow.py", "training.py", "features.py", "baselines.py", "evaluation.py",
    "historical_export.py", "certified_scope.py", "artifacts.py", "ridge_artifact.py",
)


def _code_hashes() -> dict[str, str]:
    return {name: sha256_file(Path(__file__).parent / name) for name in CODE_COMPONENTS}


@dataclass(frozen=True)
class ReconstructionInputContext(HistoricalInputContext):
    source_audit: dict[str, object]


def preceding_weekend_anchor(signal_session: date) -> date:
    calendar = exchange_calendars.get_calendar("XNYS")
    if not calendar.is_session(signal_session.isoformat()):
        raise HistoricalSafetyError("signal date must be an XNYS session")
    monday = signal_session - timedelta(days=signal_session.weekday())
    return calendar.date_to_session(
        (monday - timedelta(days=1)).isoformat(), direction="previous",
    ).date()


@dataclass(frozen=True)
class ReconstructionRequest:
    reconstruction_id: uuid.UUID
    signal_session: date
    anchor_session: date
    training_cutoff: datetime
    execution_context_id: uuid.UUID
    input_manifest_id: uuid.UUID
    manifest_hash: str
    context_hash: str
    universe_version_id: uuid.UUID

    def validate(self) -> None:
        HistoricalTrainingFence(self.anchor_session, self.training_cutoff).validate()
        if self.anchor_session != preceding_weekend_anchor(self.signal_session):
            raise HistoricalSafetyError("anchor must precede the signal week's weekend")
        monday = self.signal_session - timedelta(days=self.signal_session.weekday())
        weekend_end = datetime.combine(monday, time(), tzinfo=NEW_YORK)
        if self.training_cutoff >= weekend_end or self.training_cutoff >= datetime.now(UTC):
            raise HistoricalSafetyError("cutoff must be a completed preceding-weekend cutoff")
        for value in (self.manifest_hash, self.context_hash):
            if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                raise HistoricalSafetyError("explicit frozen SHA256 identities are required")


def _validate_sources(
    connection: object, request: ReconstructionRequest,
) -> dict[str, object]:
    """Fail closed instead of silently dropping a future revision from the frozen input."""
    source = SourceRepository(connection)  # type: ignore[arg-type]
    source.validate_context_manifest(execution_context_id=request.execution_context_id)
    context = source.read_context(execution_context_id=request.execution_context_id)
    if (
        context["input_manifest_id"] != request.input_manifest_id
        or context["context_hash"] != request.context_hash
        or context["cutoff_at"] != request.training_cutoff
        or context["knowledge_mode"] != "HISTORICAL_RECONSTRUCTION"
    ):
        raise HistoricalSafetyError("explicit frozen reconstruction context mismatch")
    manifest = connection.execute(  # type: ignore[attr-defined]
        "SELECT manifest_hash FROM ops.input_manifest WHERE input_manifest_id = %s",
        (request.input_manifest_id,),
    ).fetchone()
    if manifest is None or manifest["manifest_hash"] != request.manifest_hash:
        raise HistoricalSafetyError("explicit frozen manifest mismatch")
    rows = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT ss.source_snapshot_id, ss.source_available_at, ss.coverage_end, ss.fetched_at,
               ss.dataset_code, ss.storage_uri, ss.content_hash,
               EXISTS (
                   SELECT 1 FROM ops.data_quality_issue dqi
                   WHERE dqi.ingestion_run_id = ss.ingestion_run_id
                     AND dqi.severity = 'BLOCKING'
               ) AS blocking
        FROM ops.input_manifest_member imm
        JOIN ops.source_snapshot ss USING (source_snapshot_id)
        WHERE imm.input_manifest_id = %s
        """,
        (request.input_manifest_id,),
    ).fetchall()
    if not rows:
        raise HistoricalSafetyError("frozen training manifest is empty")
    for row in rows:
        if row["source_available_at"] > request.training_cutoff:
            raise HistoricalSafetyError("future source snapshot in training manifest")
        if row["coverage_end"] is not None and row["coverage_end"] > request.anchor_session:
            raise HistoricalSafetyError("training snapshot coverage exceeds anchor")
        if row["blocking"]:
            raise HistoricalSafetyError("blocking quality issue in training manifest")
    scopes = [
        read_scope_artifact(
            uri=row["storage_uri"], expected_sha256=row["content_hash"],
            cutoff_at=request.training_cutoff,
        )
        for row in rows if row.get("dataset_code") == DATASET_CODE
    ]
    if len(scopes) > 1:
        raise HistoricalSafetyError("Ambiguous certified eligibility scopes")
    if scopes:
        scope = scopes[0]
        if scope["universe_version_id"] != str(request.universe_version_id):
            raise HistoricalSafetyError("Certified scope universe binding mismatch")
        scope_row = next(row for row in rows if row.get("dataset_code") == DATASET_CODE)
        if (
            scope_row["source_available_at"]
            != datetime.fromisoformat(scope["data_publication_max"])
        ):
            raise HistoricalSafetyError("Certified fact publication/snapshot bound mismatch")
    # Observations acquired later are permitted, publication/revision availability is not.
    future = connection.execute(  # type: ignore[attr-defined]
        """
        WITH bound AS (
            SELECT source_snapshot_id FROM ops.input_manifest_member
            WHERE input_manifest_id = %s
        ), available AS (
            SELECT bar.source_available_at FROM bound
            JOIN market.daily_bar_observation obs USING (source_snapshot_id)
            JOIN market.daily_bar bar USING (instrument_id, session_date, source_id, revision_no)
            UNION ALL
            SELECT action.source_available_at FROM bound
            JOIN market.corporate_action_observation obs USING (source_snapshot_id)
            JOIN market.corporate_action action USING (action_id)
            UNION ALL
            SELECT greatest(uv.announced_at, uv.effective_at) FROM bound
            JOIN ref.universe_version uv USING (source_snapshot_id)
            UNION ALL
            SELECT benchmark.source_available_at FROM bound
            JOIN market.benchmark_daily_bar benchmark USING (source_snapshot_id)
        )
        SELECT count(*) FILTER (WHERE source_available_at > %s) AS violations,
               max(source_available_at) AS source_available_at_max,
               EXISTS (
                   SELECT 1 FROM bound
                   JOIN ref.universe_version uv USING (source_snapshot_id)
                   WHERE uv.as_of_date > %s
               ) AS future_universe,
               EXISTS (
                   SELECT 1 FROM bound
                   JOIN ref.universe_version uv USING (source_snapshot_id)
                   GROUP BY uv.as_of_date
                   HAVING count(DISTINCT uv.universe_version_id) > 1
               ) AS ambiguous_universe
        FROM available
        """,
        (request.input_manifest_id, request.training_cutoff, request.anchor_session),
    ).fetchone()
    if (
        future is None or future["violations"] or future["future_universe"]
        or future["ambiguous_universe"]
    ):
        raise HistoricalSafetyError("future source revision in frozen training data")
    universe = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT uv.universe_version_id FROM ref.universe_version uv
        JOIN ops.input_manifest_member imm USING (source_snapshot_id)
        JOIN ops.source_snapshot ss USING (source_snapshot_id)
        WHERE imm.input_manifest_id = %s
          AND uv.as_of_date <= %s AND ss.source_available_at <= %s
          AND uv.announced_at <= %s AND uv.effective_at <= %s
        ORDER BY uv.as_of_date DESC
        LIMIT 1
        """,
        (
            request.input_manifest_id, request.anchor_session,
            request.training_cutoff, request.training_cutoff, request.training_cutoff,
        ),
    ).fetchone()
    if universe is None or universe["universe_version_id"] != request.universe_version_id:
        raise HistoricalSafetyError("frozen anchor universe is not eligible")
    return {
        "snapshot_count": len(rows),
        "snapshot_ids_hash": _canonical_hash(
            sorted(str(row["source_snapshot_id"]) for row in rows),
        ),
        "snapshot_source_available_at_max": max(row["source_available_at"] for row in rows),
        "snapshot_fetched_at_max": max(row["fetched_at"] for row in rows),
        "normalized_future_revision_count": 0,
        "normalized_source_available_at_max": future["source_available_at_max"],
        "observation_policy": "Late acquisition allowed; source/revision availability fenced.",
        **({"certified_scope": scopes[0]} if scopes else {}),
    }


def _isolated_context(
    database: Database, request: ReconstructionRequest,
) -> ReconstructionInputContext:
    """Clone only the immutable binding, not source data, into a fresh training namespace."""
    context_hash = _canonical_hash({"contract": CONTRACT_VERSION, **asdict(request)})
    context_id = _stable_uuid("historical-challenger-context", context_hash)
    with database.connect() as connection, connection.transaction():
        audit = _validate_sources(connection, request)
        connection.execute(
            """
            INSERT INTO ops.execution_context (
                execution_context_id, input_manifest_id, cutoff_at, knowledge_mode,
                code_version, config_version, context_hash
            ) VALUES (%s, %s, %s, 'HISTORICAL_RECONSTRUCTION', %s, %s, %s)
            """,
            (
                context_id, request.input_manifest_id, request.training_cutoff,
                __version__, CONTRACT_VERSION, context_hash,
            ),
        )
    return ReconstructionInputContext(
        context_id, request.universe_version_id, request.training_cutoff, audit,
    )


def reconstruct_challenger(
    *,
    database: Database,
    settings: Settings,
    request: ReconstructionRequest,
    repository_root: Path,
    output_root: Path,
) -> PackagedArtifact:
    request.validate()
    config_root = repository_root / "config" / "analytics"
    policy_path = weekly_retraining_policy_path(config_root, DEFAULT_WEEKLY_POLICY_VERSION)
    policy = load_weekly_retraining_policy(policy_path)
    if policy.version != DEFAULT_WEEKLY_POLICY_VERSION or policy.performance_gates_enabled:
        raise HistoricalSafetyError("approved performance-suspended weekly policy is required")
    root = output_root.resolve() / str(request.reconstruction_id)
    # Exclusive reservation also prevents retrying a completed or interrupted fit in place.
    root.mkdir(parents=True, exist_ok=False)
    generated_at = datetime.now(UTC)
    training_code_hashes = _code_hashes()
    try:
        context = _isolated_context(database, request)
        export = HistoricalQlibExportService(database).export(
            start_date=request.anchor_session - timedelta(days=730),
            end_date=request.anchor_session,
            output_root=root / "qlib",
            qlib_version=version("pyqlib"),
            decision_cutoff=request.training_cutoff,
            input_context=context,
        )
        export_dir = root / "qlib" / str(export.export_run_id)
        export_manifest = json.loads((export_dir / "manifest.json").read_text(encoding="utf-8"))
        if (
            export.execution_context_id != context.execution_context_id
            or export.universe_version_id != request.universe_version_id
            or export.artifact_hash != export_manifest["content_hash"]
            or export_manifest["execution_context_id"] != str(context.execution_context_id)
        ):
            raise HistoricalSafetyError("reconstruction export binding mismatch")
        for relative, checksum in export_manifest["artifacts"].items():
            path = (export_dir / relative).resolve()
            if not path.is_relative_to(export_dir.resolve()) or sha256_file(path) != checksum:
                raise HistoricalSafetyError("reconstruction export artifact checksum mismatch")
        summary = run_training_only_workflow(
            settings=settings,
            export_dir=export_dir,
            model_config=load_versioned_config(config_root / "model_lightgbm_20d_v1.yaml"),
            label_config=load_versioned_config(config_root / "label_forward_return_20d_v1.yaml"),
            output_root=root / "training",
            reconstruction=HistoricalTrainingFence(request.anchor_session, request.training_cutoff),
            **({"certified_scope": context.source_audit["certified_scope"]}
               if context.source_audit.get("certified_scope") else {}),
        )
        return bind_fitted_challenger(
            database=database, request=request, summary=summary,
            training_execution_context_id=context.execution_context_id,
            export_dir=export_dir, repository_root=repository_root,
            output_directory=root / "artifact", generated_at=generated_at,
            training_code_hashes=training_code_hashes,
        )
    except Exception:
        (root / "FAILED").write_text(
            "Reconstruction failed; no activation was attempted. Use a new reconstruction ID.\n",
            encoding="utf-8",
        )
        raise


def bind_fitted_challenger(
    *, database: Database, request: ReconstructionRequest, summary: TrainingWorkflowSummary,
    training_execution_context_id: uuid.UUID, export_dir: Path, repository_root: Path,
    output_directory: Path, generated_at: datetime,
    training_code_hashes: dict[str, str] | None = None,
) -> PackagedArtifact:
    """Bind existing fitted winners without retraining, changing rows, or selecting substitutes."""
    request.validate()
    config_root = repository_root / "config" / "analytics"
    policy_path = weekly_retraining_policy_path(config_root, DEFAULT_WEEKLY_POLICY_VERSION)
    policy = load_weekly_retraining_policy(policy_path)
    export_manifest = json.loads((export_dir / "manifest.json").read_text(encoding="utf-8"))
    with database.connect() as connection:
        source_audit = _validate_sources(connection, request)
        registered = connection.execute(
            "SELECT * FROM analytics.model_version WHERE model_version_id = %s",
            (summary.model_version_id,),
        ).fetchone()
        export = connection.execute(
            "SELECT * FROM analytics.qlib_export_run WHERE export_run_id = %s",
            (summary.export_run_id,),
        ).fetchone()
        training_context = connection.execute(
            "SELECT * FROM ops.execution_context WHERE execution_context_id = %s",
            (training_execution_context_id,),
        ).fetchone()
    if (
        registered is None or registered["promotion_status"] != "SHADOW"
        or summary.model_purpose != "MEDIUM_20D"
        or summary.prediction_horizon_sessions != 20 or summary.return_policy != "PRICE_RETURN"
        or summary.selected_shadow_model not in {"lightgbm", "ridge"}
        or registered["model_name"] != summary.selected_shadow_model
        or registered["export_run_id"] != summary.export_run_id
        or export is None or export["execution_context_id"] != training_execution_context_id
        or export["status"] != "SUCCEEDED"
        or training_context is None
        or training_context["input_manifest_id"] != request.input_manifest_id
        or training_context["cutoff_at"] != request.training_cutoff
        or training_context["knowledge_mode"] != "HISTORICAL_RECONSTRUCTION"
        or export_manifest["execution_context_id"] != str(training_execution_context_id)
        or export_manifest["content_hash"] != export["artifact_hash"]
        or registered["metrics"] != summary.metrics[summary.selected_shadow_model]
        or policy.performance_gates_enabled
    ):
        raise HistoricalSafetyError("selected challenger/export is not a bound SHADOW 20D winner")
    evaluation = evaluate_promotion(
        policy=policy, model_purpose="MEDIUM_20D",
        challenger_metrics=summary.metrics[summary.selected_shadow_model], incumbent_metrics=None,
    )
    if any(gate.enforced and not gate.passed for gate in evaluation.gate_results.values()):
        raise HistoricalSafetyError("challenger failed retained weekly integrity gates")
    candidates = [
        name for name in ("lightgbm", "ridge")
        if name in summary.metrics and float(summary.metrics[name]["coverage"]) >= 0.8
        and int(summary.metrics[name]["test_blocks"]) >= 3
    ]
    winner = max(candidates, key=lambda name: (
        *(float(summary.metrics[name][key]) for key in (
            "rank_ic_mean", "fold_rank_ic_median", "net_top_10_return", "max_drawdown_top_10",
        )), name,
    ))
    if summary.selected_shadow_model != winner:
        raise HistoricalSafetyError("fitted challenger is not the unchanged comparison winner")
    for relative, checksum in export_manifest["artifacts"].items():
        path = (export_dir / relative).resolve()
        if not path.is_relative_to(export_dir.resolve()) or sha256_file(path) != checksum:
            raise HistoricalSafetyError("reconstruction export artifact checksum mismatch")
    packaged = package_model_artifact(
        source_directory=summary.experiment_dir, output_directory=output_directory,
        model_version_id=summary.model_version_id, model_purpose="MEDIUM_20D",
        registered_model=registered, config_root=config_root,
        allow_ridge=True,
    )
    provenance = {
            "contract_version": CONTRACT_VERSION,
            "knowledge_mode": "HISTORICAL_RECONSTRUCTION",
            "promotion_allowed": False,
            "status": "CHALLENGER_READY",
            "request": asdict(request),
            "training_execution_context_id": str(training_execution_context_id),
            "source_audit": source_audit,
            "export_run_id": str(summary.export_run_id),
            "export_content_hash": export["artifact_hash"],
            "export_manifest_sha256": sha256_file(export_dir / "manifest.json"),
            "model_version_id": str(summary.model_version_id),
            "manifest_sha256": packaged.manifest_sha256,
            "model_sha256": packaged.model_sha256,
            "model_family": packaged.manifest.model_family,
            "training_artifact_sha256": packaged.manifest.registered_artifact_sha256,
            "selection_rule": "Unchanged eligible Ridge/LightGBM comparison; no substitution",
            "policy_version": policy.version,
            "policy_sha256": sha256_file(policy_path),
            "training_code_sha256": training_code_hashes,
            "binding_code_sha256": _code_hashes(),
            "training_code_attestation": (
                "Captured before this fit" if training_code_hashes is not None
                else "No contemporaneous code hash attestation for this retained fitted checkpoint"
            ),
            "runtime_versions": {
                name: version(name)
                for name in ("pyqlib", "lightgbm", "pandas", "pyarrow", "scikit-learn", "numpy")
            },
            "weekly_gate_results": {
                name: asdict(gate) for name, gate in evaluation.gate_results.items()
            },
            "split_spec": registered["split_spec"],
            "generated_at": generated_at.isoformat(),
            "artifact_created_at": datetime.now(UTC).isoformat(),
            "limitations": [
                "Not an operational replay; acquisition may postdate historical cutoff.",
                "Universe/GICS history is limited to the explicitly frozen manifest.",
                "No incumbent comparison, activation, smoke, CAS or rollback is attempted.",
            ],
    }
    with (output_directory / "reconstruction.json").open("x", encoding="utf-8") as stream:
        json.dump(provenance, stream, default=str, indent=2, sort_keys=True)
        stream.write("\n")
    validate_reconstructed_artifact(
        manifest_path=packaged.manifest_path, manifest_sha256=packaged.manifest_sha256,
        provenance_sha256=sha256_file(output_directory / "reconstruction.json"),
        signal_session=request.signal_session, knowledge_mode="HISTORICAL_RECONSTRUCTION",
        expected_quality_mask_sha256=source_audit.get("certified_scope", {}).get(
            "quality_mask_sha256",
        ),
    )
    return packaged


def validate_reconstructed_artifact(
    *,
    manifest_path: Path,
    manifest_sha256: str,
    provenance_sha256: str,
    signal_session: date,
    knowledge_mode: str,
    expected_quality_mask_sha256: str | None = None,
) -> ArtifactManifest:
    """Admission seam for an explicit Quant artifact override, never an active assignment."""
    if knowledge_mode != "HISTORICAL_RECONSTRUCTION":
        raise HistoricalSafetyError("reconstructed artifact is not operational replay")
    provenance_path = manifest_path.parent / "reconstruction.json"
    if (
        sha256_file(manifest_path) != manifest_sha256
        or sha256_file(provenance_path) != provenance_sha256
    ):
        raise HistoricalSafetyError("reconstruction artifact/provenance checksum mismatch")
    manifest = ArtifactManifest.from_bytes(
        manifest_path.read_bytes(), expected_purpose="MEDIUM_20D",
    )
    proof = json.loads(provenance_path.read_text(encoding="utf-8"))
    cutoff = datetime.fromisoformat(proof["request"]["training_cutoff"])
    anchor = date.fromisoformat(proof["request"]["anchor_session"])
    HistoricalTrainingFence(anchor, cutoff).validate()
    split = proof["split_spec"]
    trained_scope = split.get("certified_eligibility_scope")
    if trained_scope is not None:
        if (
            expected_quality_mask_sha256 is None
            or trained_scope["quality_mask_sha256"] != expected_quality_mask_sha256
            or proof["source_audit"]["certified_scope"]["quality_mask_sha256"]
            != expected_quality_mask_sha256
        ):
            raise HistoricalSafetyError("Model and prediction context quality scopes differ")
    elif expected_quality_mask_sha256 is not None:
        raise HistoricalSafetyError("Model was not fitted under the certified quality scope")
    if (
        proof["contract_version"] != CONTRACT_VERSION
        or proof["knowledge_mode"] != "HISTORICAL_RECONSTRUCTION"
        or proof["promotion_allowed"] is not False
        or proof["status"] != "CHALLENGER_READY"
        or proof["manifest_sha256"] != manifest_sha256
        or proof["model_sha256"] != manifest.model_sha256
        or proof["model_version_id"] != str(manifest.model_version_id)
        or (
            manifest.model_family == "ridge" and (
                proof.get("model_family") != "ridge"
                or proof.get("training_artifact_sha256") != manifest.training_artifact_sha256
            )
        )
        or sha256_file(manifest_path.parent / manifest.model_file) != manifest.model_sha256
        or anchor != preceding_weekend_anchor(signal_session)
        or cutoff >= datetime.combine(signal_session, time(), tzinfo=NEW_YORK)
        or split["training_cutoff"] != cutoff.isoformat()
        or split["anchor_session"] != anchor.isoformat()
        or split["promotion_allowed"] is not False
        or proof["policy_version"] != DEFAULT_WEEKLY_POLICY_VERSION
        or proof["source_audit"]["normalized_future_revision_count"] != 0
        or datetime.fromisoformat(
            proof["source_audit"]["snapshot_source_available_at_max"],
        ) > cutoff
        or datetime.fromisoformat(split["training_data_end"]).date() > anchor
        or datetime.fromisoformat(split["training_label_exit_max"]).date() > anchor
        or datetime.fromisoformat(split["processor_fit_data_end"]).date() > anchor
        or any(
            gate["enforced"] and not gate["passed"]
            for gate in proof["weekly_gate_results"].values()
        )
        or datetime.fromisoformat(split["fit_at"]) <= cutoff
        or datetime.fromisoformat(proof["artifact_created_at"])
        < datetime.fromisoformat(split["fit_completed_at"])
    ):
        raise HistoricalSafetyError("reconstruction artifact is not bound to this signal week")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reconstruction-id", type=uuid.UUID, required=True)
    parser.add_argument("--signal-session", type=date.fromisoformat, required=True)
    parser.add_argument("--anchor-session", type=date.fromisoformat, required=True)
    parser.add_argument("--training-cutoff", type=datetime.fromisoformat, required=True)
    parser.add_argument("--execution-context-id", type=uuid.UUID, required=True)
    parser.add_argument("--input-manifest-id", type=uuid.UUID, required=True)
    parser.add_argument("--manifest-hash", required=True)
    parser.add_argument("--context-hash", required=True)
    parser.add_argument("--universe-version-id", type=uuid.UUID, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    args = vars(parser.parse_args())
    output_root = args.pop("output_root")
    repository_root = args.pop("repository_root")
    settings = Settings.from_env()
    artifact = reconstruct_challenger(
        database=Database(settings), settings=settings,
        request=ReconstructionRequest(**args),
        repository_root=repository_root, output_root=output_root,
    )
    print(json.dumps({
        "manifest": str(artifact.manifest_path),
        "manifest_sha256": artifact.manifest_sha256,
        "provenance_sha256": sha256_file(artifact.manifest_path.parent / "reconstruction.json"),
        "model_version_id": str(artifact.manifest.model_version_id),
        "promotion_allowed": False,
    }))


if __name__ == "__main__":
    main()
