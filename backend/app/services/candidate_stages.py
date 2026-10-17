from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import exchange_calendars

from backend.app.repositories.candidate_stage_runs import (
    CandidateStageConflict,
    CandidateStageRepository,
)
from backend.app.schemas.candidate_stages import (
    CandidateStageAccepted,
    CandidateStageRequest,
    CandidateStageResult,
    CandidateStageRun,
)
from sp500_candidate_engine.analytics.config import load_versioned_config
from sp500_candidate_engine.analytics.source_repository import SourceRepository
from sp500_candidate_engine.backfill import backfill_cutoff
from sp500_candidate_engine.config import Settings
from sp500_candidate_engine.database import Database, _canonical_hash

if TYPE_CHECKING:
    from backend.app.services.pipeline_execution import PipelineExecutionService

logger = logging.getLogger(__name__)
_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_PUBLIC_COLUMNS = (
    "stage_run_id", "stage", "target_session", "execution_context_id", "model_purpose",
    "retry_of_run_id", "status", "contract_hash", "input_hash", "created_at",
    "started_at", "finished_at", "failure_code", "result",
)


class StageContractChanged(ValueError):
    pass


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError("Stored candidate stage contract is not a string-keyed mapping")
    return value


class CandidateStageService:
    def __init__(
        self, database: Database, settings: Settings, *,
        execution: PipelineExecutionService | None = None,
        repository_root: Path | None = None, owner: str = "API",
    ) -> None:
        if owner not in {"API", "CLI"}:
            raise ValueError("Unknown candidate stage owner")
        self.database = database
        self.settings = settings
        self.execution = execution
        self.root = repository_root or Path(__file__).resolve().parents[3]
        self.owner = owner

    def _quantitative(self) -> PipelineExecutionService:
        if self.execution is None:
            from backend.app.services.pipeline_execution import PipelineExecutionService

            self.execution = PipelineExecutionService(self.database, self.settings)
        return self.execution

    def _context(self, payload: CandidateStageRequest) -> dict[str, object]:
        if backfill_cutoff(payload.target_session) > datetime.now(UTC):
            raise ValueError("Candidate stage requires a completed decision cutoff")
        calendar = exchange_calendars.get_calendar("XNYS")
        if not calendar.is_session(str(payload.target_session)):
            raise ValueError("Candidate stage target must be an XNYS session")
        with self.database.connect() as connection:
            source = SourceRepository(connection)
            source.validate_context_manifest(execution_context_id=payload.execution_context_id)
            context = source.read_context(execution_context_id=payload.execution_context_id)
            if context["cutoff_at"] != backfill_cutoff(payload.target_session):
                raise ValueError("Context cutoff does not match the requested target session")
            manifest = connection.execute(
                "SELECT manifest_hash FROM ops.input_manifest WHERE input_manifest_id=%s",
                (context["input_manifest_id"],),
            ).fetchone()
            if manifest is None:
                raise ValueError("Candidate stage manifest is missing")
            members = source.read_universe_members(
                execution_context_id=payload.execution_context_id,
                target_session=payload.target_session,
            )
        versions = {str(member["universe_version_id"]) for member in members}
        if len(versions) != 1:
            raise ValueError("Candidate stage requires one nonempty manifest-fenced universe")
        return {
            "execution_context_id": str(payload.execution_context_id),
            "input_manifest_id": str(context["input_manifest_id"]),
            "manifest_hash": str(manifest["manifest_hash"]),
            "context_hash": str(context["context_hash"]),
            "cutoff_at": backfill_cutoff(payload.target_session).isoformat(),
            "knowledge_mode": str(context["knowledge_mode"]),
            "universe_version_id": next(iter(versions)),
        }

    def _artifact_reference(self, purpose: str) -> dict[str, object]:
        with self.database.connect() as connection:
            active = connection.execute(
                "SELECT model_version_id,artifact_uri,artifact_hash,blob_etag,blob_version_id "
                "FROM analytics.active_model_assignment WHERE model_purpose=%s",
                (purpose,),
            ).fetchone()
        if active is not None:
            return {key: str(value) if isinstance(value, uuid.UUID) else value
                    for key, value in active.items()}
        execution = self._quantitative()
        path = execution.candidate_artifact_manifest if purpose == "SHORT_5D" \
            else execution.medium_candidate_artifact_manifest
        checksum = execution.candidate_artifact_manifest_sha256 if purpose == "SHORT_5D" \
            else execution.medium_candidate_artifact_manifest_sha256
        if path is None or not checksum:
            raise ValueError("Independent Quant requires an explicitly provisioned model artifact")
        from sp500_candidate_engine.analytics.artifacts import ArtifactManifest

        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != checksum:
            raise ValueError("Configured Quant manifest hash mismatch")
        manifest = ArtifactManifest.from_bytes(content, expected_purpose=purpose)
        return {
            "model_version_id": str(manifest.model_version_id),
            "artifact_uri": path.resolve().as_uri(), "artifact_hash": checksum,
            "blob_etag": None, "blob_version_id": None,
        }

    def capture_contract(
        self, payload: CandidateStageRequest, *, pinned: dict[str, object] | None = None,
    ) -> dict[str, object]:
        contract: dict[str, object] = {"context": self._context(payload)}
        if payload.stage == "QUANTITATIVE":
            purpose = payload.model_purpose
            assert purpose is not None
            from backend.app.services.pipeline_execution import MODEL_PURPOSE_CONTRACTS

            purpose_config = MODEL_PURPOSE_CONTRACTS[purpose]
            filenames = [
                "feature_alpha158_v1.yaml", str(purpose_config["model_config"]),
                str(purpose_config["label_config"]),
                "selection_medium_20d_v1.yaml" if purpose == "MEDIUM_20D" else "selection_v1.yaml",
            ]
            contract["quant_config"] = {
                name: load_versioned_config(self.root / "config" / "analytics" / name).config_hash
                for name in filenames
            }
            contract["artifact"] = (
                _mapping(pinned["artifact"]) if pinned is not None
                else self._artifact_reference(purpose)
            )
        else:
            from sp500_candidate_engine.llm_preselection.service import load_runtime_llm_config

            config = load_runtime_llm_config(self.root)
            contract["llm_policy"] = {
                "policy_version": config.policy_version,
                "policy_hash": config.versioned.config_hash,
                "prompt_version": config.prompt_version,
                "evidence_schema_version": config.evidence_schema_version,
            }
            if payload.stage == "LLM_PRESELECTION":
                from sp500_candidate_engine.llm_preselection.ranker import LlmRankerSettings

                settings = LlmRankerSettings.from_env()
                contract["deployment"] = {
                    "endpoint": settings.endpoint, "deployment": settings.deployment,
                    "api_version": settings.api_version,
                }
            else:
                from sp500_candidate_engine.fusion.config import fusion_enabled, load_fusion_policy

                if not fusion_enabled() or not config.event_policy:
                    raise ValueError("Independent Fusion requires enabled Fusion and event policy")
                policy = load_fusion_policy(self.root)
                quant_policy = load_versioned_config(
                    self.root / "config" / "analytics" / "selection_medium_20d_v1.yaml"
                )
                contract["fusion"] = {
                    "policy_version": policy.version, "policy_hash": policy.config_hash,
                    "quant_policy_version": quant_policy.version,
                    "quant_policy_hash": quant_policy.config_hash,
                }
        return contract

    def accept(
        self, payload: CandidateStageRequest, key: str, *, retry_of: uuid.UUID | None = None,
    ) -> CandidateStageAccepted:
        if not _KEY.fullmatch(key):
            raise ValueError("Invalid Idempotency-Key")
        raw = payload.model_dump(mode="json")
        request_hash = _canonical_hash({"request": raw, "retry_of_run_id": retry_of})
        with self.database.connect() as connection, connection.transaction():
            from backend.app.services.pipeline_execution import ACCEPTANCE_LOCK

            connection.execute("SELECT pg_advisory_xact_lock(%s)", (ACCEPTANCE_LOCK,))
            repository = CandidateStageRepository(connection)
            repository.lock("key:" + key)
            existing = repository.by_key(key)
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise CandidateStageConflict("Idempotency-Key already has a different request")
                accepted = CandidateStageAccepted.model_validate({
                    "stage_run_id": existing["stage_run_id"], "status": existing["status"],
                    "status_url": f"/api/v1/candidate-stage-runs/{existing['stage_run_id']}",
                })
                accepted._is_replay = True
                return accepted
            active_collection = connection.execute(
                """
                SELECT process_run_id FROM ops.backend_pipeline_request
                WHERE status IN ('PENDING','RUNNING')
                UNION ALL
                SELECT process_run_id FROM ops.process_run
                WHERE status IN ('PENDING','RUNNING')
                LIMIT 1
                """
            ).fetchone()
            if active_collection is not None:
                raise CandidateStageConflict(
                    "Collection/daily pipeline is active; retry explicitly"
                )
            previous = repository.get(retry_of) if retry_of is not None else None
            if previous is not None:
                if previous["status"] not in {"FAILED", "SHORTFALL"}:
                    raise CandidateStageConflict("Only failed/shortfall stage runs can be retried")
                if previous["request_payload"] != raw:
                    raise CandidateStageConflict("Retry must preserve the original request")
            pinned = _mapping(previous["contract"]) if previous is not None else None
            contract = self.capture_contract(payload, pinned=pinned)
            contract_hash = _canonical_hash(contract)
            if previous is not None and previous["contract_hash"] != contract_hash:
                raise CandidateStageConflict(
                    "Retry contract changed; create a new explicit request"
                )
            run_id = uuid.uuid4()
            row = repository.create(
                run_id=run_id, payload=raw, request_hash=request_hash,
                contract=contract, contract_hash=contract_hash,
                input_hash=_canonical_hash({"request": raw, "contract_hash": contract_hash}),
                key=key, retry_of=retry_of, owner=self.owner,
            )
        return CandidateStageAccepted.model_validate({
            "stage_run_id": run_id, "status": row["status"],
            "status_url": f"/api/v1/candidate-stage-runs/{run_id}",
        })

    def retry(self, run_id: uuid.UUID, key: str) -> CandidateStageAccepted:
        with self.database.connect() as connection:
            row = CandidateStageRepository(connection).get(run_id)
        return self.accept(
            CandidateStageRequest.model_validate(row["request_payload"]), key, retry_of=run_id,
        )

    def get(self, run_id: uuid.UUID) -> CandidateStageRun:
        with self.database.connect() as connection:
            row = CandidateStageRepository(connection).get(run_id)
        return CandidateStageRun.model_validate({key: row[key] for key in _PUBLIC_COLUMNS})

    def reconcile_interrupted(self) -> int:
        with self.database.connect() as connection, connection.transaction():
            return CandidateStageRepository(connection).reconcile()

    def execute_background(self, run_id: uuid.UUID) -> None:
        asyncio.run(self.execute(run_id))

    async def execute(self, run_id: uuid.UUID) -> None:
        with self.database.connect() as connection, connection.transaction():
            row = CandidateStageRepository(connection).claim(run_id)
        if row is None:
            raise CandidateStageConflict("Candidate stage was already claimed or completed")
        try:
            payload = CandidateStageRequest.model_validate(row["request_payload"])
            pinned = _mapping(row["contract"])
            contract = await asyncio.to_thread(self.capture_contract, payload, pinned=pinned)
            if _canonical_hash(contract) != row["contract_hash"]:
                raise StageContractChanged("Candidate stage configuration changed after acceptance")
            result, status, failure_code = await self._run(payload, pinned)
            if (
                status not in {"SUCCEEDED", "SHORTFALL", "FAILED"}
                or (status == "SUCCEEDED" and failure_code is not None)
                or (status != "SUCCEEDED" and not failure_code)
                or (status == "SUCCEEDED" and (
                    result.selection_run_id is None
                    or (payload.model_purpose != "SHORT_5D" and result.candidate_count != 20)
                    or (payload.model_purpose == "SHORT_5D"
                        and not 5 <= result.candidate_count <= 10)
                ))
            ):
                raise ValueError("Candidate stage returned an invalid terminal result")
        except BaseException as error:
            logger.exception("candidate_stage_failed stage_run_id=%s", run_id)
            result, status = None, "FAILED"
            failure_code = (
                "CONTRACT_CHANGED" if isinstance(error, StageContractChanged)
                else "INTERRUPTED" if isinstance(error, (KeyboardInterrupt, asyncio.CancelledError))
                else type(error).__name__
            )
            with self.database.connect() as connection, connection.transaction():
                CandidateStageRepository(connection).finish(run_id, status, result, failure_code)
            raise
        with self.database.connect() as connection, connection.transaction():
            CandidateStageRepository(connection).finish(
                run_id, status, result.model_dump(mode="json"), failure_code
            )

    async def _run(
        self, payload: CandidateStageRequest, contract: dict[str, object],
    ) -> tuple[CandidateStageResult, str, str | None]:
        if payload.stage == "QUANTITATIVE":
            return await asyncio.to_thread(self._run_quantitative, payload, contract)
        if payload.stage == "LLM_PRESELECTION":
            from sp500_candidate_engine.llm_preselection.ranker import LlmRankerSettings
            from sp500_candidate_engine.llm_preselection.service import (
                LlmPreselectionService,
                load_runtime_llm_config,
            )

            service = LlmPreselectionService(
                self.database, load_runtime_llm_config(self.root), LlmRankerSettings.from_env()
            )
            try:
                summary = await service.run(
                    target_session=payload.target_session,
                    execution_context_id=payload.execution_context_id,
                )
            finally:
                await service.ranker.aclose()
            return CandidateStageResult(
                selection_run_id=summary.selection_run_id,
                llm_ranking_run_id=summary.llm_ranking_run_id,
                candidate_count=summary.selected_count, reused=summary.reused,
            ), summary.status, summary.failure_code
        from sp500_candidate_engine.fusion.config import load_fusion_policy
        from sp500_candidate_engine.fusion.service import FusionService
        from sp500_candidate_engine.llm_preselection.service import load_runtime_llm_config

        quant = load_versioned_config(
            self.root / "config" / "analytics" / "selection_medium_20d_v1.yaml"
        )
        fusion = await asyncio.to_thread(
            FusionService(
                self.database, load_fusion_policy(self.root), load_runtime_llm_config(self.root),
                quant.version, quant.config_hash,
            ).run,
            context_id=payload.execution_context_id, target_session=payload.target_session,
            quant_id=payload.quant_selection_run_id, llm_id=payload.llm_preselection_run_id,
        )
        return CandidateStageResult(
            fusion_run_id=fusion.fusion_run_id, selection_run_id=fusion.fusion_run_id,
            candidate_count=fusion.selected_count, reused=fusion.reused,
        ), fusion.status, fusion.failure_code

    def _run_quantitative(
        self, payload: CandidateStageRequest, contract: dict[str, object],
    ) -> tuple[CandidateStageResult, str, str | None]:
        from backend.app.services.model_artifacts import ArtifactBinding, ModelArtifactLoader
        from sp500_candidate_engine.analytics.historical_export import HistoricalInputContext

        purpose = payload.model_purpose
        assert purpose is not None
        artifact = _mapping(contract["artifact"])
        execution = self._quantitative()
        loader = ModelArtifactLoader(execution.workspace_dir / "models" / "cache")
        materialized = loader.load(ArtifactBinding(
            model_purpose=purpose, artifact_uri=str(artifact["artifact_uri"]),
            artifact_hash=str(artifact["artifact_hash"]),
            blob_etag=str(artifact["blob_etag"]) if artifact.get("blob_etag") is not None else None,
            blob_version_id=str(artifact["blob_version_id"])
            if artifact.get("blob_version_id") is not None else None,
        ))
        if str(materialized.manifest.model_version_id) != artifact["model_version_id"]:
            raise ValueError("Pinned Quant model identity mismatch")
        context = _mapping(contract["context"])
        from sp500_candidate_engine.selection.policy import SelectionShortfallError

        if purpose == "MEDIUM_20D":
            from sp500_candidate_engine.fusion.repository import FusionRepository

            quant_policy = load_versioned_config(
                self.root / "config" / "analytics" / "selection_medium_20d_v1.yaml"
            )
            with self.database.connect() as connection:
                existing = FusionRepository(connection).find_quantitative(
                    context_id=payload.execution_context_id, target_session=payload.target_session,
                    policy_version=quant_policy.version, policy_hash=quant_policy.config_hash,
                )
            if existing is not None and str(existing["model_version_id"]) == str(
                materialized.manifest.model_version_id
            ):
                return CandidateStageResult.model_validate({
                    "selection_run_id": existing["selection_run_id"],
                    "scoring_run_id": existing["scoring_run_id"],
                    "model_version_id": existing["model_version_id"],
                    "candidate_count": existing["candidate_count"], "reused": True,
                }), "SUCCEEDED", None
        with self.database.connect(autocommit=True) as lock_connection:
            key = f"quant-export:{payload.execution_context_id}"
            lock_connection.execute("SELECT pg_advisory_lock(hashtextextended(%s,0))", (key,))
            try:
                summary = execution.run_candidate_inference(
                    self.settings, target_date=payload.target_session, repository_root=self.root,
                    model_purpose=purpose, artifact_override=materialized,
                    input_context=HistoricalInputContext(
                        payload.execution_context_id,
                        uuid.UUID(str(context["universe_version_id"])),
                        backfill_cutoff(payload.target_session),
                    ),
                )
            except SelectionShortfallError:
                logger.warning("independent_quantitative_selection_shortfall")
                return CandidateStageResult(candidate_count=0, reused=False), \
                    "SHORTFALL", "INSUFFICIENT_ELIGIBLE_CANDIDATES"
            finally:
                lock_connection.execute(
                    "SELECT pg_advisory_unlock(hashtextextended(%s,0))", (key,)
                )
        return CandidateStageResult(
            selection_run_id=summary.selection_run_id, scoring_run_id=summary.scoring_run_id,
            model_version_id=summary.model_version_id,
            candidate_count=summary.candidate_count, reused=False,
        ), "SUCCEEDED", None
