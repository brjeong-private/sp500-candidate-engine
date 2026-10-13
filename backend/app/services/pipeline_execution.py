from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import exchange_calendars

from backend.app.schemas.execution import PipelineRunAccepted, PipelineRunRequest
from sp500_candidate_engine.backfill import backfill_cutoff, build_backfill_plan
from sp500_candidate_engine.batch_pipeline import run_backfill_process, run_daily_process
from sp500_candidate_engine.config import Settings
from sp500_candidate_engine.database import Database
from sp500_candidate_engine.models import UTC
from sp500_candidate_engine.source_harness import (
    CandidateCollectionPlan,
    validate_candidate_collection_plan,
)

logger = logging.getLogger(__name__)
ACCEPTANCE_LOCK = 517_017_001
INTERRUPTED_REASON = "API background execution interrupted by process restart; resubmit explicitly"
IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
MODEL_PURPOSE_CONTRACTS = {
    "SHORT_5D": {
        "model_config": "model_lightgbm_v2.yaml",
        "label_config": "label_forward_return_5d_v2.yaml",
        "label_semantics": "RAW_STOCK_5D_RETURN",
        "score_semantics": "PREDICTED_5D_RETURN",
        "horizon_sessions": 5,
        "return_policy": "PRICE_RETURN",
    },
    "MEDIUM_20D": {
        "model_config": "model_lightgbm_20d_v1.yaml",
        "label_config": "label_forward_return_20d_v1.yaml",
        "label_semantics": "RAW_STOCK_20D_RETURN",
        "score_semantics": "PREDICTED_20D_RETURN",
        "horizon_sessions": 20,
        "return_policy": "PRICE_RETURN",
    },
}


class PipelineConflict(RuntimeError):
    pass


class PipelineExecutionService:
    """Durable acceptance, not a durable queue. Only the API owns these requests."""

    def __init__(
        self,
        database: Database,
        settings: Settings,
        *,
        candidate_artifact_manifest: Path | None = None,
        candidate_artifact_manifest_sha256: str | None = None,
        workspace_dir: Path | None = None,
    ) -> None:
        self.database = database
        self.settings = settings
        self.repository_root = Path(__file__).parents[3]
        configured_workspace = os.environ.get("BACKEND_WORKSPACE_DIR")
        self.workspace_dir = (
            workspace_dir
            or (Path(configured_workspace) if configured_workspace else self.repository_root)
        ).resolve()
        configured_manifest = os.environ.get(
            "BACKEND_CANDIDATE_ARTIFACT_MANIFEST_SHORT_5D"
        ) or os.environ.get("BACKEND_CANDIDATE_ARTIFACT_MANIFEST")
        self.candidate_artifact_manifest = candidate_artifact_manifest or (
            Path(configured_manifest) if configured_manifest else None
        )
        if (
            self.candidate_artifact_manifest is not None
            and not self.candidate_artifact_manifest.is_absolute()
        ):
            self.candidate_artifact_manifest = (
                self.workspace_dir / self.candidate_artifact_manifest
            ).resolve()
        self.candidate_artifact_manifest_sha256 = (
            candidate_artifact_manifest_sha256
            or os.environ.get("BACKEND_CANDIDATE_ARTIFACT_MANIFEST_SHA256_SHORT_5D")
            or os.environ.get("BACKEND_CANDIDATE_ARTIFACT_MANIFEST_SHA256")
        )
        configured_medium_manifest = os.environ.get(
            "BACKEND_CANDIDATE_ARTIFACT_MANIFEST_MEDIUM_20D"
        )
        self.medium_candidate_artifact_manifest = (
            Path(configured_medium_manifest) if configured_medium_manifest else None
        )
        if (
            self.medium_candidate_artifact_manifest is not None
            and not self.medium_candidate_artifact_manifest.is_absolute()
        ):
            self.medium_candidate_artifact_manifest = (
                self.workspace_dir / self.medium_candidate_artifact_manifest
            ).resolve()
        self.medium_candidate_artifact_manifest_sha256 = os.environ.get(
            "BACKEND_CANDIDATE_ARTIFACT_MANIFEST_SHA256_MEDIUM_20D"
        )

    def validate_request(
        self, request: PipelineRunRequest, *, now: datetime | None = None
    ) -> tuple[date, ...]:
        now = now or datetime.now(UTC)
        start = request.date or request.start_date
        end = request.date or request.end_date
        assert start is not None and end is not None
        if end >= now.date():
            raise ValueError("Only completed historical trading sessions may be requested")
        # Validate provider history before asking the finite calendar for a potentially
        # enormous range. The engine's policy accounts for leap-year history boundaries.
        validate_candidate_collection_plan(
            CandidateCollectionPlan(
                target_date=start,
                evaluated_on=now.date(),
                massive_requests=1,
                alpha_vantage_requests=0,
            ),
            self.settings.source_policies(),
        )
        plan = build_backfill_plan(
            start_date=start,
            end_date=end,
            evaluated_on=now.date(),
            policies=self.settings.source_policies(),
        )
        if request.mode == "DAILY" and plan.sessions != (start,):
            raise ValueError("DAILY date must be an XNYS trading session")
        if any(backfill_cutoff(session) > now for session in plan.sessions):
            raise ValueError("Session data is not complete before the engine cutoff")
        return plan.sessions

    def session_eligibility(
        self, target: date, *, now: datetime | None = None
    ) -> tuple[bool, bool]:
        now = now or datetime.now(UTC)
        calendar = exchange_calendars.get_calendar("XNYS")
        sessions = calendar.sessions_in_range(target, target)
        is_session = len(sessions) == 1 and sessions[0].date() == target
        return is_session, is_session and backfill_cutoff(target) <= now

    def accept(self, request: PipelineRunRequest, idempotency_key: str) -> PipelineRunAccepted:
        if IDEMPOTENCY_KEY_PATTERN.fullmatch(idempotency_key) is None:
            raise ValueError("Invalid Idempotency-Key")
        canonical_payload = request.model_dump(mode="json", exclude_none=True)
        request_hash = hashlib.sha256(
            json.dumps(
                canonical_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
            ).encode()
        ).hexdigest()
        with self.database.connect() as connection, connection.transaction():
            connection.execute("SELECT pg_advisory_xact_lock(%s)", (ACCEPTANCE_LOCK,))
            existing = connection.execute(
                """
                SELECT process_run_id, request_hash
                FROM ops.backend_pipeline_request
                WHERE idempotency_key = %s
                """,
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise PipelineConflict(
                        "Idempotency-Key was already used with a different request"
                    )
                accepted = PipelineRunAccepted(
                    process_run_id=existing["process_run_id"],
                    status_url=f"/api/v1/pipeline-runs/{existing['process_run_id']}",
                )
                accepted._is_replay = True
                return accepted
            sessions = self.validate_request(request)
            process_run_id = uuid.uuid4()
            start = request.date or request.start_date
            end = request.date or request.end_date
            assert start is not None and end is not None
            active = connection.execute(
                """
                SELECT process_run_id FROM ops.backend_pipeline_request
                WHERE status IN ('PENDING', 'RUNNING')
                UNION ALL
                SELECT p.process_run_id FROM ops.process_run p
                WHERE p.status IN ('PENDING', 'RUNNING')
                  AND NOT EXISTS (
                    SELECT 1 FROM ops.backend_pipeline_request r
                    WHERE r.process_run_id = p.process_run_id
                  )
                LIMIT 1
                """
            ).fetchone()
            if active is not None:
                raise PipelineConflict("A pipeline is already active; provider quotas are shared")
            self._insert_process(
                connection, process_run_id, request.mode, start, end, len(sessions)
            )
            connection.execute(
                """
                INSERT INTO ops.backend_pipeline_request(
                    process_run_id, mode, status, request_payload,
                    idempotency_key, request_hash
                ) VALUES (%s, %s, 'PENDING', %s, %s, %s)
                """,
                (
                    process_run_id,
                    request.mode,
                    request.model_dump_json(),
                    idempotency_key,
                    request_hash,
                ),
            )
        return PipelineRunAccepted(
            process_run_id=process_run_id,
            status_url=f"/api/v1/pipeline-runs/{process_run_id}",
        )

    def _insert_process(
        self,
        connection,
        run_id: uuid.UUID,
        mode: str,
        start: date,
        end: date,
        total: int,
        parent: uuid.UUID | None = None,
    ) -> None:
        log_uri = (self.settings.log_dir / "processes" / f"{run_id}.jsonl").resolve().as_uri()
        connection.execute(
            """
            INSERT INTO ops.process_run(
                process_run_id, process_type, status, range_start, range_end,
                total_dates, started_at, heartbeat_at, log_uri, metadata,
                parent_process_run_id
            ) VALUES (%s, %s, 'PENDING', %s, %s, %s, now(), now(), %s, %s, %s)
            """,
            (
                run_id,
                mode,
                start,
                end,
                total,
                log_uri,
                json.dumps({"owner": "backend_api"}),
                parent,
            ),
        )

    def execute_background(self, process_run_id: uuid.UUID) -> None:
        """FastAPI runs this synchronous callable in its worker thread, not its loop."""
        try:
            asyncio.run(self.execute(process_run_id))
        except Exception:
            # execute already persists the failure; propagate so server logs expose it.
            logger.exception("API pipeline failed: %s", process_run_id)
            raise

    async def execute(self, process_run_id: uuid.UUID) -> None:
        claimed = False
        try:
            with self.database.connect() as connection, connection.transaction():
                row = connection.execute(
                    """
                    UPDATE ops.backend_pipeline_request SET status = 'RUNNING'
                    WHERE process_run_id = %s AND status = 'PENDING'
                    RETURNING request_payload
                    """,
                    (process_run_id,),
                ).fetchone()
            if row is None:
                raise PipelineConflict("Request is missing or already claimed")
            claimed = True
            payload = row["request_payload"]
            request = (
                PipelineRunRequest.model_validate_json(payload)
                if isinstance(payload, str)
                else PipelineRunRequest.model_validate(payload)
            )
            sessions = self.validate_request(request)
            if request.mode == "DAILY":
                assert request.date is not None
                result = await run_daily_process(
                    self.settings,
                    target_date=request.date,
                    run_candidates=True,
                    process_run_id=process_run_id,
                    candidate_runner=self.run_candidate_inference,
                    model_purpose=request.model_purpose,
                )
                if result["status"] == "SUCCEEDED":
                    candidate = result.get("candidate_run")
                    if (
                        not isinstance(candidate, dict)
                        or str(candidate.get("price_session_date")) != request.date.isoformat()
                    ):
                        raise RuntimeError("Candidate result does not match the requested session")
            elif request.mode == "BACKFILL":
                assert request.start_date is not None and request.end_date is not None
                result = await run_backfill_process(
                    self.settings,
                    start_date=request.start_date,
                    end_date=request.end_date,
                    auto_retry=request.auto_retry if request.auto_retry is not None else True,
                    process_run_id=process_run_id,
                )
            else:
                result = await self._execute_range(process_run_id, sessions)
            status = str(result["status"])
            with self.database.connect() as connection:
                connection.execute(
                    """
                    UPDATE ops.process_run SET metadata = metadata || %s::jsonb
                    WHERE process_run_id = %s
                    """,
                    (json.dumps({"execution_result": result}, default=str), process_run_id),
                )
            self._finish(
                process_run_id,
                status,
                None if status == "SUCCEEDED" else "Collection failed; inspect date attempts",
            )
        except BaseException as error:
            if claimed:
                self._finish(process_run_id, "FAILED", f"{type(error).__name__}: {error}")
            raise

    async def _execute_range(
        self, parent_id: uuid.UUID, sessions: tuple[date, ...]
    ) -> dict[str, object]:
        children: list[tuple[date, uuid.UUID]] = []
        with self.database.connect() as connection, connection.transaction():
            connection.execute(
                "UPDATE ops.process_run SET status = 'RUNNING' WHERE process_run_id = %s",
                (parent_id,),
            )
            for session in sessions:
                child_id = uuid.uuid4()
                self._insert_process(connection, child_id, "DAILY", session, session, 1, parent_id)
                children.append((session, child_id))
        successes = 0
        for session, child_id in children:
            try:
                result = await run_daily_process(
                    self.settings,
                    target_date=session,
                    run_candidates=False,
                    process_run_id=child_id,
                )
                successes += result["status"] == "SUCCEEDED"
            except Exception as error:
                self._finish_process(child_id, "FAILED", f"{type(error).__name__}: {error}")
                logger.exception("RANGE child failed: %s", child_id)
            with self.database.connect() as connection:
                connection.execute(
                    """
                    UPDATE ops.process_run SET completed_dates = completed_dates + 1,
                        success_dates = %s, failed_dates = completed_dates + 1 - %s,
                        heartbeat_at = now() WHERE process_run_id = %s
                    """,
                    (successes, successes, parent_id),
                )
        return {
            "status": (
                "SUCCEEDED"
                if successes == len(sessions)
                else "PARTIAL_SUCCESS"
                if successes
                else "FAILED"
            )
        }

    def _finish_process(self, run_id: uuid.UUID, status: str, reason: str | None) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE ops.process_run SET status = %s, finished_at = now(),
                    heartbeat_at = now(), metadata = metadata || %s::jsonb
                WHERE process_run_id = %s
                """,
                (status, json.dumps({"failure_reason": reason}), run_id),
            )

    def _finish(self, run_id: uuid.UUID, status: str, reason: str | None) -> None:
        with self.database.connect() as connection, connection.transaction():
            connection.execute(
                """
                UPDATE ops.backend_pipeline_request SET status = %s, failure_reason = %s,
                    finished_at = now() WHERE process_run_id = %s
                """,
                (status, reason, run_id),
            )
            connection.execute(
                """
                UPDATE ops.process_run SET status = %s, finished_at = now(),
                    heartbeat_at = now(), metadata = metadata || %s::jsonb
                WHERE process_run_id = %s
                """,
                (status, json.dumps({"failure_reason": reason}), run_id),
            )
            if status == "FAILED":
                connection.execute(
                    """
                    UPDATE ops.process_run SET status = 'FAILED', finished_at = now(),
                        metadata = metadata || %s::jsonb
                    WHERE parent_process_run_id = %s AND status IN ('PENDING', 'RUNNING')
                    """,
                    (json.dumps({"failure_reason": reason}), run_id),
                )
                connection.execute(
                    """
                    UPDATE ops.process_date_status d SET status = 'FAILED',
                        failure_reason = %s, completed = true, finished_at = now(),
                        retry_required = true, retry_status = 'FAILED', updated_at = now()
                    FROM ops.process_run p
                    WHERE d.process_run_id = p.process_run_id
                      AND (p.process_run_id = %s OR p.parent_process_run_id = %s)
                      AND d.status IN ('PENDING', 'RUNNING')
                    """,
                    (reason, run_id, run_id),
                )

    def reconcile_interrupted(self) -> int:
        """Startup only, under the single-instance/worker deployment contract."""
        with self.database.connect() as connection, connection.transaction():
            connection.execute("SELECT pg_advisory_xact_lock(%s)", (ACCEPTANCE_LOCK,))
            rows = connection.execute(
                """
                UPDATE ops.backend_pipeline_request SET status = 'FAILED',
                    failure_reason = %s, finished_at = now()
                WHERE status IN ('PENDING', 'RUNNING') RETURNING process_run_id
                """,
                (INTERRUPTED_REASON,),
            ).fetchall()
            ids = [row["process_run_id"] for row in rows]
            if ids:
                connection.execute(
                    """
                    UPDATE ops.process_run SET status = 'FAILED', finished_at = now(),
                        metadata = metadata || %s::jsonb
                    WHERE process_run_id = ANY(%s::uuid[])
                       OR (parent_process_run_id = ANY(%s::uuid[])
                           AND status IN ('PENDING', 'RUNNING'))
                    """,
                    (json.dumps({"failure_reason": INTERRUPTED_REASON}), ids, ids),
                )
                connection.execute(
                    """
                    UPDATE ops.process_date_status d SET status = 'FAILED',
                        failure_reason = %s, completed = true, finished_at = now(),
                        retry_required = true, retry_status = 'FAILED', updated_at = now()
                    FROM ops.process_run p
                    WHERE d.process_run_id = p.process_run_id
                      AND (p.process_run_id = ANY(%s::uuid[])
                           OR p.parent_process_run_id = ANY(%s::uuid[]))
                      AND d.status IN ('PENDING', 'RUNNING')
                    """,
                    (INTERRUPTED_REASON, ids, ids),
                )
        return len(ids)

    def candidate_history_start(self, target: date) -> date:
        from sp500_candidate_engine.analytics.config import load_versioned_config

        root = self.repository_root
        feature = load_versioned_config(
            root / "config" / "analytics" / "feature_alpha158_v1.yaml",
            required_keys=("lookback_sessions",),
        ).payload
        required = int(feature["lookback_sessions"]) + 1
        calendar = exchange_calendars.get_calendar("XNYS")
        dates = calendar.sessions_in_range(target - timedelta(days=required * 3), target)
        start = dates[-required].date()
        validate_candidate_collection_plan(
            CandidateCollectionPlan(
                target_date=start,
                evaluated_on=datetime.now(UTC).date(),
                massive_requests=0,
                alpha_vantage_requests=0,
            ),
            self.settings.source_policies(),
        )
        return start

    def run_candidate_inference(
        self,
        settings: Settings,
        *,
        target_date: date,
        repository_root: Path,
        model_purpose: str = "SHORT_5D",
    ) -> SimpleNamespace:
        """Use a provisioned model without training, fitting processors, or fallback."""
        try:
            contract = MODEL_PURPOSE_CONTRACTS[model_purpose]
        except KeyError as error:
            raise RuntimeError(f"Unsupported model purpose: {model_purpose}") from error
        if model_purpose == "SHORT_5D":
            configured_manifest = self.candidate_artifact_manifest
            configured_manifest_sha256 = self.candidate_artifact_manifest_sha256
        else:
            configured_manifest = self.medium_candidate_artifact_manifest
            configured_manifest_sha256 = self.medium_candidate_artifact_manifest_sha256
        if configured_manifest is None or not configured_manifest_sha256:
            raise RuntimeError(
                f"DAILY {model_purpose} inference requires its explicitly provisioned candidate "
                "artifact manifest and SHA256; API DAILY never trains a model or falls back "
                "between model purposes"
            )
        from importlib.metadata import version

        import lightgbm
        import numpy as np
        import pandas as pd

        from sp500_candidate_engine.analytics.config import load_versioned_config
        from sp500_candidate_engine.analytics.features import (
            Alpha158FeatureService,
            normalize_alpha158_frame,
        )
        from sp500_candidate_engine.analytics.historical_export import HistoricalQlibExportService
        from sp500_candidate_engine.analytics.phase45_workflow import TrainingDataRepository
        from sp500_candidate_engine.analytics.score_repository import ScoreRepository
        from sp500_candidate_engine.analytics.scoring import rank_daily_scores
        from sp500_candidate_engine.database import _canonical_hash
        from sp500_candidate_engine.selection.policy import (
            CandidateMetadata,
            SelectionPolicy,
            select_candidates,
        )
        from sp500_candidate_engine.selection.repository import SelectionRepository
        from sp500_candidate_engine.selection.service import candidate_result_payload

        del settings
        manifest_path = configured_manifest.resolve()
        manifest_bytes = manifest_path.read_bytes()
        if hashlib.sha256(manifest_bytes).hexdigest() != configured_manifest_sha256:
            raise RuntimeError("Candidate artifact manifest SHA256 mismatch")
        manifest = json.loads(manifest_bytes)
        if manifest.get("schema_version") != 2:
            raise RuntimeError("Unsupported candidate artifact manifest version")
        expected_manifest_contract = {
            "model_purpose": model_purpose,
            "label_semantics": contract["label_semantics"],
            "prediction_semantics": contract["score_semantics"],
            "horizon_sessions": contract["horizon_sessions"],
        }
        if any(
            manifest.get(key) != expected
            for key, expected in expected_manifest_contract.items()
        ):
            raise RuntimeError("Candidate artifact manifest model-purpose contract mismatch")
        model_id = uuid.UUID(manifest["model_version_id"])
        model_path = (manifest_path.parent / manifest["model_file"]).resolve()
        if not model_path.is_relative_to(manifest_path.parent):
            raise RuntimeError("Model file must reside inside the provisioned artifact directory")
        model_hash = hashlib.sha256(model_path.read_bytes()).hexdigest()
        if model_hash != manifest["model_sha256"]:
            raise RuntimeError("Candidate model artifact SHA256 mismatch")
        # Installed code/config/SQL remain in the deployment; generated data belongs
        # in the configurable persistent workspace, never in Oryx extraction files.
        root = self.repository_root
        del repository_root
        feature_config = load_versioned_config(
            root / "config" / "analytics" / "feature_alpha158_v1.yaml",
            required_keys=("expected_dimension", "lookback_sessions", "raw_feature_run"),
        )
        model_config = load_versioned_config(
            root / "config" / "analytics" / str(contract["model_config"]),
            required_keys=("version", "prediction_semantics"),
        )
        label_config = load_versioned_config(
            root / "config" / "analytics" / str(contract["label_config"]),
            required_keys=("horizon_sessions",),
        )
        selection_config = load_versioned_config(
            root / "config" / "analytics" / "selection_v1.yaml",
            required_keys=(
                "minimum_candidates",
                "maximum_candidates",
                "sector_cap",
                "relaxed_sector_cap",
            ),
        )
        effective_model_hash = _canonical_hash(
            {
                "model_config_hash": model_config.config_hash,
                "label_config_hash": label_config.config_hash,
            }
        )
        if (
            manifest["feature_config_hash"] != feature_config.config_hash
            or manifest["model_config_hash"] != effective_model_hash
            or model_config.payload["prediction_semantics"] != contract["score_semantics"]
            or int(label_config.payload["horizon_sessions"])
            != contract["horizon_sessions"]
        ):
            raise RuntimeError("Provisioned candidate model/config contract mismatch")
        raw_contract = feature_config.payload["raw_feature_run"]
        if raw_contract["infer_processors"] or raw_contract["learn_processors"]:
            raise RuntimeError("Pinned inference currently supports raw, unprocessed Alpha158 only")
        feature_names = tuple(manifest["feature_names"])
        if len(feature_names) != int(feature_config.payload["expected_dimension"]):
            raise RuntimeError("Provisioned model feature dimension mismatch")
        with self.database.connect() as connection:
            model_row = connection.execute(
                """
                SELECT m.*, e.end_date AS training_export_end
                FROM analytics.model_version m
                JOIN analytics.qlib_export_run e ON e.export_run_id = m.export_run_id
                WHERE m.model_version_id = %s
                """,
                (model_id,),
            ).fetchone()
        if (
            model_row is None
            or model_row["artifact_hash"] != model_hash
            or model_row["model_name"] != "lightgbm"
            or str(model_row["version"]) != str(model_config.payload["version"])
            or model_row["config_hash"] != effective_model_hash
            or model_row["label_semantics"] != contract["label_semantics"]
            or model_row["model_purpose"] != model_purpose
            or model_row["return_policy"] != contract["return_policy"]
            or model_row["processor_version_id"] is not None
            or model_row["promotion_status"] not in {"SHADOW", "CHAMPION"}
            or model_row["training_export_end"] >= target_date
        ):
            raise RuntimeError(
                "Pinned registry model is incompatible or includes future training data"
            )
        booster = lightgbm.Booster(model_file=str(model_path))
        if booster.num_feature() != len(feature_names):
            raise RuntimeError("LightGBM artifact feature dimension mismatch")
        start_date = self.candidate_history_start(target_date)
        export = HistoricalQlibExportService(self.database).export(
            start_date=start_date,
            end_date=target_date,
            output_root=self.workspace_dir / "data" / "output" / "qlib",
            qlib_version=version("pyqlib"),
            decision_cutoff=backfill_cutoff(target_date),
        )
        with self.database.connect() as connection:
            context = connection.execute(
                "SELECT cutoff_at FROM ops.execution_context WHERE execution_context_id = %s",
                (export.execution_context_id,),
            ).fetchone()
        if context is None or context["cutoff_at"] > backfill_cutoff(target_date):
            raise RuntimeError("Inference export context exceeds the requested decision cutoff")
        cutoff_at = context["cutoff_at"]
        export_dir = self.workspace_dir / "data" / "output" / "qlib" / str(export.export_run_id)
        features = normalize_alpha158_frame(
            Alpha158FeatureService()
            .compute_raw(
                provider_uri=export_dir / "qlib_data",
                instruments="all",
                start_date=target_date,
                end_date=target_date,
            )
            .frame
        )
        if tuple(str(column) for column in features.columns) != feature_names:
            raise RuntimeError("Alpha158 feature names/order do not match the pinned model")
        sessions = exchange_calendars.get_calendar("XNYS").sessions_in_range(
            start_date, target_date
        )
        prices, _, membership, metadata = TrainingDataRepository(self.database).load(
            export_run_id=export.export_run_id,
            calendar=tuple(sessions),
        )
        target_timestamp = pd.Timestamp(target_date)
        eligible = membership[target_timestamp]
        complete_prices = prices[["open", "close"]].notna().all(axis=1)
        history_counts = complete_prices.groupby(level="instrument").sum()
        target_features = features.loc[
            features.index.get_level_values("datetime") == target_timestamp
        ]
        valid_symbols = {
            symbol for symbol in eligible if history_counts.get(symbol, 0) == len(sessions)
        }
        valid_rows = target_features.index.get_level_values("instrument").isin(
            valid_symbols
        ) & np.isfinite(target_features.to_numpy(dtype=float)).all(axis=1)
        target_features = target_features.loc[valid_rows]
        if target_features.empty:
            raise RuntimeError("No eligible candidates have complete warm-up history and features")
        prediction = pd.Series(
            booster.predict(target_features.to_numpy(), num_threads=1),
            index=target_features.index,
            name="score",
        )
        raw_scores = {}
        sectors = {}
        candidate_metadata = {}
        for (_, symbol), score in prediction.items():
            if not np.isfinite(score) or symbol not in metadata.index:
                continue
            row = metadata.loc[symbol]
            instrument_id = row["instrument_id"]
            raw_scores[instrument_id] = float(score)
            sectors[instrument_id] = row["sector"]
            candidate_metadata[instrument_id] = CandidateMetadata(
                instrument_id=instrument_id,
                issuer_id=row["issuer_id"],
                symbol=str(row["symbol"]),
                sector=row["sector"],
            )
        scores = rank_daily_scores(
            session_date=target_date,
            raw_scores=raw_scores,
            sectors=sectors,
        )
        policy_payload = selection_config.payload
        policy = SelectionPolicy(
            minimum_candidates=int(policy_payload["minimum_candidates"]),
            maximum_candidates=int(policy_payload["maximum_candidates"]),
            sector_cap=int(policy_payload["sector_cap"]),
            relaxed_sector_cap=int(policy_payload["relaxed_sector_cap"]),
        )
        selected = select_candidates(scores=scores, metadata=candidate_metadata, policy=policy)
        generated_at = datetime.now(UTC)
        with self.database.connect() as connection, connection.transaction():
            score_repository = ScoreRepository(connection)
            scoring_run_id = score_repository.create_run(
                session_date=target_date,
                execution_context_id=export.execution_context_id,
                export_run_id=export.export_run_id,
                model_version_id=model_id,
                universe_version_id=export.universe_version_id,
                config_hash=effective_model_hash,
                score_semantics=str(contract["score_semantics"]),
                prediction_horizon_sessions=int(contract["horizon_sessions"]),
            )
            score_repository.write_scores(
                scoring_run_id=scoring_run_id,
                scores=scores,
                prediction_horizon=int(contract["horizon_sessions"]),
            )
            selection_run_id = SelectionRepository(connection).persist(
                price_session_date=target_date,
                cutoff_at=cutoff_at,
                generated_at=generated_at,
                valid_until=None,
                scoring_run_id=scoring_run_id,
                policy_version=str(policy_payload["version"]),
                requested_count=policy.maximum_candidates,
                result=selected,
            )
        payload = candidate_result_payload(
            selection_run_id=selection_run_id,
            scoring_run_id=scoring_run_id,
            model_version_id=model_id,
            execution_context_id=export.execution_context_id,
            price_session_date=target_date,
            cutoff_at=cutoff_at,
            generated_at=generated_at,
            policy_version=str(policy_payload["version"]),
            result=selected,
            model_status=str(model_row["promotion_status"]),
            promotion_gate_passed=False,
        )
        candidate_dir = self.workspace_dir / "data" / "output" / "candidates"
        candidate_dir.mkdir(parents=True, exist_ok=True)
        candidate_path = candidate_dir / f"{target_date}-{selection_run_id}.json"
        candidate_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        return SimpleNamespace(
            price_session_date=target_date,
            model_version_id=model_id,
            scoring_run_id=scoring_run_id,
            selection_run_id=selection_run_id,
            candidate_count=len(selected.candidates),
            model_status=str(model_row["promotion_status"]),
            promotion_gate_passed=False,
        )
