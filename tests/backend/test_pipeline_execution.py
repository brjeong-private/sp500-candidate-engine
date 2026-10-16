import asyncio
import hashlib
import json
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app.routers.execution import get_execution_service, router
from backend.app.schemas.execution import PipelineRunRequest
from backend.app.services import pipeline_execution as execution
from sp500_candidate_engine.source_harness import SourcePolicies


class Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class MemoryDatabase:
    """SQL-shaped test double: transactions serialize via the acceptance lock."""

    def __init__(self):
        self.runs = {}
        self.requests = {}
        self.statements = []
        self.lock = threading.RLock()

    @contextmanager
    def connect(self):
        yield self

    @contextmanager
    def transaction(self):
        with self.lock:
            yield

    def execute(self, sql, params=()):
        statement = " ".join(sql.split())
        self.statements.append(statement)
        if statement.startswith("SELECT pg_advisory"):
            return Result()
        if statement.startswith("SELECT process_run_id, request_hash"):
            for key, row in self.requests.items():
                if row["idempotency_key"] == params[0]:
                    return Result([{"process_run_id": key, "request_hash": row["request_hash"]}])
            return Result()
        if statement.startswith("SELECT process_run_id FROM ops.backend_pipeline_request"):
            active = [
                key for key, row in self.requests.items() if row["status"] in {"PENDING", "RUNNING"}
            ]
            active += [
                key
                for key, row in self.runs.items()
                if row["status"] in {"PENDING", "RUNNING"} and key not in self.requests
            ]
            return Result([{"process_run_id": key} for key in active[:1]])
        if statement.startswith("INSERT INTO ops.process_run"):
            key, mode, start, end, total, log, metadata, parent = params
            self.runs[key] = dict(
                mode=mode,
                start=start,
                end=end,
                total=total,
                log=log,
                metadata=json.loads(metadata),
                parent=parent,
                status="PENDING",
            )
        elif statement.startswith("INSERT INTO ops.backend_pipeline_request"):
            key, mode, payload, idempotency_key, request_hash = params
            self.requests[key] = dict(
                mode=mode,
                request_payload=payload,
                status="PENDING",
                idempotency_key=idempotency_key,
                request_hash=request_hash,
            )
        elif "RETURNING request_payload" in statement:
            row = self.requests.get(params[0])
            if row is None or row["status"] != "PENDING":
                return Result()
            row["status"] = "RUNNING"
            return Result([{"request_payload": row["request_payload"]}])
        elif "RETURNING process_run_id" in statement:
            keys = []
            for key, row in self.requests.items():
                if row["status"] in {"PENDING", "RUNNING"}:
                    row.update(status="FAILED", failure_reason=params[0])
                    keys.append({"process_run_id": key})
            return Result(keys)
        elif statement.startswith("UPDATE ops.backend_pipeline_request SET status = %s"):
            status, reason, key = params
            self.requests[key].update(status=status, failure_reason=reason)
        elif statement.startswith("UPDATE ops.process_run SET status = %s"):
            status, metadata, key = params
            self.runs[key]["status"] = status
            self.runs[key]["metadata"].update(json.loads(metadata))
        elif statement.startswith("UPDATE ops.process_run SET status = 'FAILED'"):
            if "ANY" in statement:
                metadata, ids, _ = params
                for key, row in self.runs.items():
                    if key in ids or (
                        row["parent"] in ids and row["status"] in {"PENDING", "RUNNING"}
                    ):
                        row["status"] = "FAILED"
                        row["metadata"].update(json.loads(metadata))
            else:
                metadata, parent = params
                for row in self.runs.values():
                    if row["parent"] == parent and row["status"] in {"PENDING", "RUNNING"}:
                        row["status"] = "FAILED"
                        row["metadata"].update(json.loads(metadata))
        return Result()


@pytest.fixture
def service():
    settings = SimpleNamespace(
        log_dir=Path("data") / "logs",
        source_policies=lambda: SourcePolicies(),
    )
    return execution.PipelineExecutionService(MemoryDatabase(), settings)


def daily():
    return PipelineRunRequest(mode="DAILY", date=date(2026, 10, 8), with_candidates=True)


def test_daily_model_purpose_defaults_to_short_and_accepts_medium():
    assert daily().model_purpose == "SHORT_5D"
    assert (
        PipelineRunRequest(
            mode="DAILY",
            date=date(2026, 10, 8),
            with_candidates=True,
            model_purpose="MEDIUM_20D",
        ).model_purpose
        == "MEDIUM_20D"
    )


def test_idempotency_migration_is_expand_compatible():
    migration = (
        Path(__file__).parents[2] / "sql" / "020_backend_pipeline_idempotency.sql"
    ).read_text(encoding="utf-8")
    normalized = " ".join(migration.split())
    assert "ALTER COLUMN idempotency_key DROP NOT NULL" in normalized
    assert "ALTER COLUMN request_hash DROP NOT NULL" in normalized
    assert "(idempotency_key IS NULL) = (request_hash IS NULL)" in normalized
    assert "WHERE idempotency_key IS NOT NULL" in normalized
    assert "SET NOT NULL" not in normalized


@pytest.mark.parametrize(
    "payload",
    [
        {"mode": "DAILY", "date": "2026-10-08", "with_candidates": False},
        {"mode": "DAILY", "date": "2026-10-08", "with_candidates": True, "auto_retry": True},
        {
            "mode": "RANGE",
            "start_date": "2026-10-08",
            "end_date": "2026-10-09",
            "with_candidates": True,
        },
        {"mode": "BACKFILL", "start_date": "2026-10-09", "end_date": "2026-10-08"},
        {
            "mode": "BACKFILL",
            "start_date": "2026-10-08",
            "end_date": "2026-10-09",
            "with_candidates": False,
        },
        {
            "mode": "RANGE",
            "start_date": "2026-10-08",
            "end_date": "2026-10-09",
            "with_candidates": False,
            "model_purpose": "SHORT_5D",
        },
        {"mode": "DAILY", "date": "2026-10-08", "with_candidates": "true"},
    ],
)
def test_schema_rejects_invalid_mode_fields(payload):
    with pytest.raises(ValidationError):
        PipelineRunRequest.model_validate(payload)


def test_session_completion_future_and_provider_boundaries(service):
    now = datetime(2026, 10, 11, 3, tzinfo=UTC)
    assert service.validate_request(daily(), now=now) == (date(2026, 10, 8),)
    for target in (date(2026, 10, 10), date(2026, 10, 12), date(2023, 10, 8)):
        with pytest.raises(ValueError):
            service.validate_request(
                PipelineRunRequest(mode="DAILY", date=target, with_candidates=True), now=now
            )
    # A closed session is still incomplete until the configured next-day 05:30 NY cutoff.
    with pytest.raises(ValueError):
        service.validate_request(daily(), now=datetime(2026, 10, 9, 2, tzinfo=UTC))


def test_session_eligibility_uses_exchange_calendar_and_cutoff(service):
    assert service.session_eligibility(
        date(2026, 10, 9),
        now=datetime(2026, 10, 10, 10, tzinfo=UTC),
    ) == (True, True)
    assert service.session_eligibility(
        date(2026, 10, 10),
        now=datetime(2026, 10, 11, 10, tzinfo=UTC),
    ) == (False, False)
    assert service.session_eligibility(
        date(2026, 10, 9),
        now=datetime(2026, 10, 10, 8, tzinfo=UTC),
    ) == (True, False)


def test_acceptance_persists_same_id_then_executes_daily_and_candidates(service, monkeypatch):
    run = service.accept(daily(), "daily-2026-10-08")
    assert service.database.runs[run.process_run_id]["status"] == "PENDING"
    assert service.database.requests[run.process_run_id]["status"] == "PENDING"
    runner = AsyncMock(
        return_value={
            "status": "SUCCEEDED",
            "candidate_run": {"price_session_date": date(2026, 10, 8)},
        }
    )
    monkeypatch.setattr(execution, "run_daily_process", runner)
    monkeypatch.setattr(service, "candidate_history_start", lambda _: date(2025, 12, 1))
    service.execute_background(run.process_run_id)
    assert runner.call_args.kwargs["process_run_id"] == run.process_run_id
    assert runner.call_args.kwargs["run_candidates"] is True
    assert callable(runner.call_args.kwargs["candidate_runner"])
    assert runner.call_args.kwargs["model_purpose"] == "SHORT_5D"
    assert "candidate_history_start" not in runner.call_args.kwargs
    assert service.database.requests[run.process_run_id]["status"] == "SUCCEEDED"


def test_same_idempotency_key_and_canonical_payload_reuses_run(service):
    first = service.accept(daily(), "daily-2026-10-08")
    replay = service.accept(
        PipelineRunRequest.model_validate(
            {
                "with_candidates": True,
                "date": "2026-10-08",
                "mode": "DAILY",
                "auto_retry": None,
            }
        ),
        "daily-2026-10-08",
    )
    assert replay.process_run_id == first.process_run_id
    assert replay.status_url == first.status_url
    assert replay._is_replay is True
    assert len(service.database.requests) == 1


def test_same_idempotency_key_with_different_payload_conflicts(service):
    service.accept(daily(), "pipeline-request")
    different = PipelineRunRequest(
        mode="RANGE",
        start_date=date(2026, 10, 8),
        end_date=date(2026, 10, 8),
        with_candidates=False,
    )
    with pytest.raises(execution.PipelineConflict, match="different request"):
        service.accept(different, "pipeline-request")
    assert len(service.database.requests) == 1


@pytest.mark.parametrize(
    "key",
    ["", " leading", "contains space", "é", "x" * 129, "/path", "line\nbreak"],
)
def test_service_rejects_unsafe_idempotency_keys(service, key):
    with pytest.raises(ValueError, match="Invalid Idempotency-Key"):
        service.accept(daily(), key)
    assert not service.database.requests


def test_background_failure_is_persisted_and_not_swallowed(service, monkeypatch):
    run = service.accept(daily(), "daily-2026-10-08")
    monkeypatch.setattr(service, "candidate_history_start", lambda _: date(2025, 12, 1))
    monkeypatch.setattr(
        execution, "run_daily_process", AsyncMock(side_effect=RuntimeError("failed"))
    )
    with pytest.raises(RuntimeError, match="failed"):
        service.execute_background(run.process_run_id)
    row = service.database.requests[run.process_run_id]
    assert row["status"] == "FAILED"
    assert "RuntimeError: failed" in row["failure_reason"]


def test_collection_failure_status_is_not_success(service, monkeypatch):
    run = service.accept(daily(), "daily-2026-10-08")
    monkeypatch.setattr(service, "candidate_history_start", lambda _: date(2025, 12, 1))
    monkeypatch.setattr(
        execution, "run_daily_process", AsyncMock(return_value={"status": "FAILED"})
    )
    service.execute_background(run.process_run_id)
    assert service.database.requests[run.process_run_id]["status"] == "FAILED"


def test_missing_or_stale_candidate_cannot_succeed(service, monkeypatch):
    run = service.accept(daily(), "daily-2026-10-08")
    monkeypatch.setattr(service, "candidate_history_start", lambda _: date(2025, 12, 1))
    monkeypatch.setattr(
        execution,
        "run_daily_process",
        AsyncMock(
            return_value={
                "status": "SUCCEEDED",
                "candidate_run": {"price_session_date": date(2026, 10, 7)},
            }
        ),
    )
    with pytest.raises(RuntimeError, match="requested session"):
        service.execute_background(run.process_run_id)
    assert service.database.requests[run.process_run_id]["status"] == "FAILED"


def test_global_atomic_acceptance_blocks_across_modes_and_duplicate_pending(service):
    other = PipelineRunRequest(
        mode="BACKFILL", start_date=date(2026, 10, 8), end_date=date(2026, 10, 9)
    )

    def accept(request):
        try:
            return service.accept(request, f"{request.mode.lower()}-request")
        except execution.PipelineConflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        accepted = list(pool.map(accept, (daily(), other)))
    assert sum(value is not None for value in accepted) == 1
    assert len(service.database.requests) == 1
    assert any("pg_advisory_xact_lock" in sql for sql in service.database.statements)
    with pytest.raises(execution.PipelineConflict):
        service.accept(daily(), "another-request")


def test_running_conflict_and_claim_cannot_execute_twice(service, monkeypatch):
    run = service.accept(daily(), "daily-2026-10-08")
    service.database.requests[run.process_run_id]["status"] = "RUNNING"
    with pytest.raises(execution.PipelineConflict):
        service.accept(daily(), "another-request")
    with pytest.raises(execution.PipelineConflict):
        service.execute_background(run.process_run_id)
    assert service.database.requests[run.process_run_id]["status"] == "RUNNING"


def test_range_explicit_parent_child_ids_and_trading_sessions(service, monkeypatch):
    request = PipelineRunRequest(
        mode="RANGE",
        start_date=date(2026, 10, 8),
        end_date=date(2026, 10, 10),
        with_candidates=False,
    )
    run = service.accept(request, "range-2026-10-08-10")
    runner = AsyncMock(return_value={"status": "SUCCEEDED"})
    monkeypatch.setattr(execution, "run_daily_process", runner)
    service.execute_background(run.process_run_id)
    calls = [call.kwargs for call in runner.call_args_list]
    assert [call["target_date"] for call in calls] == [date(2026, 10, 8), date(2026, 10, 9)]
    ids = [call["process_run_id"] for call in calls]
    assert len(set(ids + [run.process_run_id])) == 3
    assert all(call["run_candidates"] is False for call in calls)
    assert all(service.database.runs[key]["parent"] == run.process_run_id for key in ids)


def test_backfill_reuses_accepted_id_and_retry_policy(service, monkeypatch):
    request = PipelineRunRequest(
        mode="BACKFILL",
        start_date=date(2026, 10, 8),
        end_date=date(2026, 10, 9),
        auto_retry=False,
    )
    run = service.accept(request, "backfill-2026-10-08-09")
    runner = AsyncMock(return_value={"status": "SUCCEEDED"})
    monkeypatch.setattr(execution, "run_backfill_process", runner)
    service.execute_background(run.process_run_id)
    assert runner.call_args.kwargs["process_run_id"] == run.process_run_id
    assert runner.call_args.kwargs["auto_retry"] is False


@pytest.mark.parametrize("status", ["PENDING", "RUNNING"])
def test_interrupted_pending_and_running_reconcile_only_api_owned(service, status):
    run = service.accept(daily(), "daily-2026-10-08")
    service.database.requests[run.process_run_id]["status"] = status
    cli_id = uuid.uuid4()
    child_id = uuid.uuid4()
    service.database.runs[cli_id] = dict(status="RUNNING", parent=None, metadata={})
    service.database.runs[child_id] = dict(status="RUNNING", parent=run.process_run_id, metadata={})
    assert service.reconcile_interrupted() == 1
    assert service.database.requests[run.process_run_id]["status"] == "FAILED"
    assert "interrupted" in service.database.requests[run.process_run_id]["failure_reason"]
    assert service.database.runs[child_id]["status"] == "FAILED"
    assert service.database.runs[cli_id]["status"] == "RUNNING"
    assert service.reconcile_interrupted() == 0


def test_api_authentication_and_202(service, monkeypatch):
    app = FastAPI()
    app.include_router(router)
    app.state.backend_settings = SimpleNamespace(api_key="test-only-key")
    app.dependency_overrides[get_execution_service] = lambda: service
    background = MagicMock()
    monkeypatch.setattr(service, "execute_background", background)
    with TestClient(app) as client:
        for headers in ({}, {"X-API-Key": "wrong"}):
            assert (
                client.post(
                    "/api/v1/pipeline-runs",
                    json=daily().model_dump(mode="json"),
                    headers={**headers, "Idempotency-Key": "daily-2026-10-08"},
                ).status_code
                == 401
            )
        assert not service.database.requests
        response = client.post(
            "/api/v1/pipeline-runs",
            json=daily().model_dump(mode="json"),
            headers={
                "X-API-Key": "test-only-key",
                "Idempotency-Key": "daily-2026-10-08",
            },
        )
    assert response.status_code == 202
    key = uuid.UUID(response.json()["process_run_id"])
    assert key in service.database.requests
    background.assert_called_once_with(key)
    assert response.json()["status_url"].endswith(str(key))


def test_api_requires_valid_idempotency_key_and_replay_does_not_reschedule(service, monkeypatch):
    app = FastAPI()
    app.include_router(router)
    app.state.backend_settings = SimpleNamespace(api_key="test-only-key")
    app.dependency_overrides[get_execution_service] = lambda: service
    background = MagicMock()
    monkeypatch.setattr(service, "execute_background", background)
    payload = daily().model_dump(mode="json")
    auth = {"X-API-Key": "test-only-key"}
    with TestClient(app) as client:
        assert client.post("/api/v1/pipeline-runs", json=payload, headers=auth).status_code == 422
        invalid = client.post(
            "/api/v1/pipeline-runs",
            json=payload,
            headers={**auth, "Idempotency-Key": "contains space"},
        )
        assert invalid.status_code == 422
        first = client.post(
            "/api/v1/pipeline-runs",
            json=payload,
            headers={**auth, "Idempotency-Key": "daily-2026-10-08"},
        )
        replay = client.post(
            "/api/v1/pipeline-runs",
            json=payload,
            headers={**auth, "Idempotency-Key": "daily-2026-10-08"},
        )
    assert first.status_code == replay.status_code == 202
    assert replay.json() == first.json()
    background.assert_called_once()


def test_api_same_key_different_payload_returns_409(service, monkeypatch):
    app = FastAPI()
    app.include_router(router)
    app.state.backend_settings = SimpleNamespace(api_key="test-only-key")
    app.dependency_overrides[get_execution_service] = lambda: service
    monkeypatch.setattr(service, "execute_background", MagicMock())
    headers = {
        "X-API-Key": "test-only-key",
        "Idempotency-Key": "pipeline-request",
    }
    with TestClient(app) as client:
        first = client.post(
            "/api/v1/pipeline-runs",
            json=daily().model_dump(mode="json"),
            headers=headers,
        )
        conflict = client.post(
            "/api/v1/pipeline-runs",
            json={
                "mode": "RANGE",
                "start_date": "2026-10-08",
                "end_date": "2026-10-08",
                "with_candidates": False,
            },
            headers=headers,
        )
    assert first.status_code == 202
    assert conflict.status_code == 409


def test_candidate_history_covers_inference_warmup_without_training_window(service):
    start = service.candidate_history_start(date(2026, 10, 8))
    sessions = execution.exchange_calendars.get_calendar("XNYS").sessions_in_range(
        start, date(2026, 10, 8)
    )
    assert len(sessions) == 60 + 1


def test_sync_background_wrapper_does_not_use_callers_event_loop(service, monkeypatch):
    threads = []

    async def runner(_):
        threads.append(threading.get_ident())
        asyncio.get_running_loop()

    monkeypatch.setattr(service, "execute", runner)
    app = FastAPI()
    app.include_router(router)
    app.state.backend_settings = SimpleNamespace(api_key="test-only-key")
    app.dependency_overrides[get_execution_service] = lambda: service
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/pipeline-runs",
            json=daily().model_dump(mode="json"),
            headers={
                "X-API-Key": "test-only-key",
                "Idempotency-Key": "daily-2026-10-08",
            },
        )
    assert response.status_code == 202
    assert threads and threads[0] != threading.get_ident()


def test_actual_daily_resumes_accepted_id_exports_before_candidate(service, monkeypatch):
    from sp500_candidate_engine import batch_pipeline, candidate_pipeline
    from sp500_candidate_engine.analytics import historical_export

    run_id = uuid.uuid4()
    settings = service.settings
    tracker = MagicMock()
    tracker.finalize.return_value = {"status": "SUCCEEDED"}
    tracker_factory = MagicMock()
    tracker_factory.return_value.__enter__.return_value = tracker
    database = MagicMock()
    monkeypatch.setattr(batch_pipeline, "Database", lambda _: database)
    monkeypatch.setattr(batch_pipeline, "ProcessTracker", tracker_factory)
    writer = MagicMock()
    writer.path = Path("data") / "logs" / "processes" / f"{run_id}.jsonl"
    writer.path = writer.path.resolve()
    monkeypatch.setattr(batch_pipeline, "ProcessLogWriter", lambda *_: writer)
    monkeypatch.setattr(
        batch_pipeline,
        "collect_production_inputs",
        AsyncMock(
            return_value=SimpleNamespace(
                universe_count=5,
                changed_bars=5,
                changed_actions=0,
                changed_events=0,
                missing_bars=0,
            )
        ),
    )
    order = []

    def export(self, **kwargs):
        order.append("export")
        assert kwargs["start_date"] == date(2025, 12, 1)
        assert kwargs["end_date"] == date(2026, 10, 8)

    def candidates(*args, **kwargs):
        order.append("candidates")
        return SimpleNamespace(
            price_session_date=date(2026, 10, 8),
            model_version_id=uuid.uuid4(),
            scoring_run_id=uuid.uuid4(),
            selection_run_id=uuid.uuid4(),
            candidate_count=5,
            promotion_gate_passed=False,
        )

    monkeypatch.setattr(historical_export.HistoricalQlibExportService, "export", export)
    monkeypatch.setattr(candidate_pipeline, "run_candidate_date", candidates)
    monkeypatch.setattr("importlib.metadata.version", lambda _: "test")
    result = asyncio.run(
        batch_pipeline.run_daily_process(
            settings,
            target_date=date(2026, 10, 8),
            run_candidates=True,
            process_run_id=run_id,
            candidate_history_start=date(2025, 12, 1),
        )
    )
    tracker.create_run.assert_not_called()
    tracker.resume_run.assert_called_once_with(run_id, log_uri=writer.path.as_uri())
    database.migrate.assert_not_called()
    assert batch_pipeline.collect_production_inputs.call_args.kwargs["migrate_database"] is False
    assert result["process_run_id"] == str(run_id)
    assert result["candidate_run"]["candidate_count"] == 5
    assert order == ["export", "candidates"]


def test_unprovisioned_api_inference_fails_without_training(service):
    with pytest.raises(RuntimeError, match="API DAILY never trains"):
        service.run_candidate_inference(
            service.settings,
            target_date=date(2026, 10, 8),
            repository_root=Path(__file__).parents[2],
        )


def test_medium_inference_never_falls_back_to_short_artifact(service):
    service.candidate_artifact_manifest = Path("short-manifest.json")
    service.candidate_artifact_manifest_sha256 = "short-hash"
    with pytest.raises(RuntimeError, match="MEDIUM_20D.*never trains.*falls back"):
        service.run_candidate_inference(
            service.settings,
            target_date=date(2026, 10, 8),
            repository_root=Path(__file__).parents[2],
            model_purpose="MEDIUM_20D",
        )


@pytest.mark.parametrize(
    "violation",
    [None, "manifest_hash", "model_hash", "future_training", "feature_order", "registry_hash"],
)
@pytest.mark.parametrize(
    (
        "model_purpose",
        "model_filename",
        "label_filename",
        "label_semantics",
        "score_semantics",
        "horizon",
        "model_version",
    ),
    [
        (
            "SHORT_5D",
            "model_lightgbm_v2.yaml",
            "label_forward_return_5d_v2.yaml",
            "RAW_STOCK_5D_RETURN",
            "PREDICTED_5D_RETURN",
            5,
            "2",
        ),
        (
            "MEDIUM_20D",
            "model_lightgbm_20d_v1.yaml",
            "label_forward_return_20d_v1.yaml",
            "RAW_STOCK_20D_RETURN",
            "PREDICTED_20D_RETURN",
            20,
            "1",
        ),
    ],
)
def test_pinned_inference_exports_warmup_predicts_and_reuses_model_without_training(
    service,
    monkeypatch,
    violation,
    model_purpose,
    model_filename,
    label_filename,
    label_semantics,
    score_semantics,
    horizon,
    model_version,
):
    import numpy as np
    import pandas as pd

    from sp500_candidate_engine.analytics import historical_export, phase45_workflow
    from sp500_candidate_engine.analytics.config import load_versioned_config
    from sp500_candidate_engine.analytics.features import Alpha158FeatureService
    from sp500_candidate_engine.analytics.score_repository import ScoreRepository
    from sp500_candidate_engine.database import _canonical_hash
    from sp500_candidate_engine.selection.repository import SelectionRepository

    target = date(2026, 10, 8)
    root = Path(__file__).parents[2]
    model = load_versioned_config(
        root / "config" / "analytics" / model_filename, required_keys=("version",)
    )
    label = load_versioned_config(
        root / "config" / "analytics" / label_filename,
        required_keys=("horizon_sessions",),
    )
    feature = load_versioned_config(
        root / "config" / "analytics" / "feature_alpha158_v1.yaml",
        required_keys=("expected_dimension",),
    )
    config_hash = _canonical_hash(
        {
            "model_config_hash": model.config_hash,
            "label_config_hash": label.config_hash,
        }
    )
    model_id = uuid.uuid4()
    model_bytes = b"explicit-pinned-model"
    model_hash = hashlib.sha256(model_bytes).hexdigest()
    names = [f"feature-{index}" for index in range(158)]
    manifest = json.dumps(
        {
            "schema_version": 2,
            "model_purpose": model_purpose,
            "label_semantics": label_semantics,
            "prediction_semantics": score_semantics,
            "horizon_sessions": horizon,
            "model_version_id": str(model_id),
            "model_file": "lightgbm.txt",
            "model_sha256": model_hash,
            "feature_config_hash": feature.config_hash,
            "model_config_hash": config_hash,
            "feature_names": names,
        }
    ).encode()
    manifest_path = root / "test-artifact-store" / "manifest.json"
    if model_purpose == "SHORT_5D":
        service.candidate_artifact_manifest = manifest_path
        service.candidate_artifact_manifest_sha256 = hashlib.sha256(manifest).hexdigest()
    else:
        service.medium_candidate_artifact_manifest = manifest_path
        service.medium_candidate_artifact_manifest_sha256 = hashlib.sha256(manifest).hexdigest()
    if violation == "manifest_hash":
        if model_purpose == "SHORT_5D":
            service.candidate_artifact_manifest_sha256 = "invalid"
        else:
            service.medium_candidate_artifact_manifest_sha256 = "invalid"
    if violation == "model_hash":
        model_bytes = b"tampered-model"
    monkeypatch.setattr(
        Path, "read_bytes", lambda path: manifest if path.name == "manifest.json" else model_bytes
    )
    monkeypatch.setattr(Path, "mkdir", MagicMock())
    writes = MagicMock()
    monkeypatch.setattr(Path, "write_text", writes)
    booster = MagicMock()
    booster.num_feature.return_value = 158
    booster.predict.return_value = np.arange(5, dtype=float)
    constructor = MagicMock(return_value=booster)
    monkeypatch.setitem(sys.modules, "lightgbm", SimpleNamespace(Booster=constructor))
    monkeypatch.setattr("importlib.metadata.version", lambda _: "test")
    export_id, context_id, universe_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    export = MagicMock(
        return_value=SimpleNamespace(
            export_run_id=export_id,
            execution_context_id=context_id,
            universe_version_id=universe_id,
        )
    )
    monkeypatch.setattr(historical_export.HistoricalQlibExportService, "export", export)
    connection = MagicMock()
    connection.execute.side_effect = lambda sql, params: (
        Result(
            [
                dict(
                    artifact_hash=model_hash if violation != "registry_hash" else "invalid",
                    model_name="lightgbm",
                    version=model_version,
                    config_hash=config_hash,
                    label_semantics=label_semantics,
                    model_purpose=model_purpose,
                    return_policy="PRICE_RETURN",
                    processor_version_id=None,
                    promotion_status="SHADOW",
                    training_export_end=(
                        date(2026, 10, 9) if violation == "future_training" else date(2026, 10, 7)
                    ),
                )
            ]
        )
        if "SELECT m.*" in sql
        else Result([{"cutoff_at": execution.backfill_cutoff(target)}])
    )
    database = MagicMock()
    database.connect.return_value.__enter__.return_value = connection
    service.database = database
    symbols = [f"I{uuid.uuid4().hex.upper()}" for _ in range(5)]
    index = pd.MultiIndex.from_product(
        [[pd.Timestamp(target)], symbols], names=["datetime", "instrument"]
    )
    raw_features = pd.DataFrame(np.ones((5, 158)), index=index, columns=names)
    if violation == "feature_order":
        raw_features = raw_features[names[::-1]]
    compute = MagicMock(return_value=SimpleNamespace(frame=raw_features))
    monkeypatch.setattr(Alpha158FeatureService, "compute_raw", compute)
    sessions = execution.exchange_calendars.get_calendar("XNYS").sessions_in_range(
        service.candidate_history_start(target), target
    )
    price_index = pd.MultiIndex.from_product([sessions, symbols], names=["datetime", "instrument"])
    prices = pd.DataFrame(
        np.ones((len(price_index), 2)), index=price_index, columns=["open", "close"]
    )
    metadata = pd.DataFrame(
        [
            dict(
                instrument_id=uuid.uuid4(),
                issuer_id=uuid.uuid4(),
                symbol=f"T{index}",
                sector=f"S{index}",
            )
            for index in range(5)
        ],
        index=symbols,
    )
    monkeypatch.setattr(
        phase45_workflow.TrainingDataRepository,
        "load",
        lambda *args, **kwargs: (
            prices,
            None,
            {pd.Timestamp(target): set(symbols)},
            metadata,
        ),
    )
    train = MagicMock(side_effect=AssertionError("API inference must not train"))
    monkeypatch.setattr(phase45_workflow, "train_qlib_lightgbm", train)
    scoring_id, selection_id = uuid.uuid4(), uuid.uuid4()
    create_score = MagicMock(return_value=scoring_id)
    monkeypatch.setattr(ScoreRepository, "create_run", create_score)
    write_scores = MagicMock()
    monkeypatch.setattr(ScoreRepository, "write_scores", write_scores)
    persist = MagicMock(return_value=selection_id)
    monkeypatch.setattr(SelectionRepository, "persist", persist)
    if violation is not None:
        with pytest.raises(RuntimeError):
            service.run_candidate_inference(
                service.settings,
                target_date=target,
                repository_root=root,
                model_purpose=model_purpose,
            )
        train.assert_not_called()
        booster.predict.assert_not_called()
        return
    result = service.run_candidate_inference(
        service.settings,
        target_date=target,
        repository_root=root,
        model_purpose=model_purpose,
    )
    assert result.model_version_id == model_id
    assert result.scoring_run_id == scoring_id
    assert result.selection_run_id == selection_id
    assert result.candidate_count == 5
    assert (
        export.call_args.kwargs["output_root"] == service.workspace_dir / "data" / "output" / "qlib"
    )
    assert export.call_args.kwargs["decision_cutoff"] == execution.backfill_cutoff(target)
    assert compute.call_args.kwargs["start_date"] == target
    assert compute.call_args.kwargs["end_date"] == target
    assert create_score.call_args.kwargs["model_version_id"] == model_id
    assert create_score.call_args.kwargs["score_semantics"] == score_semantics
    assert create_score.call_args.kwargs["prediction_horizon_sessions"] == horizon
    assert write_scores.call_args.kwargs["prediction_horizon"] == horizon
    assert persist.call_args.kwargs["cutoff_at"] == execution.backfill_cutoff(target)
    train.assert_not_called()
    booster.predict.assert_called_once()
    writes.assert_called_once()


def test_workspace_and_pinned_manifest_environment_keep_code_separate(service, monkeypatch):
    root = Path(__file__).parents[2]
    monkeypatch.setenv("BACKEND_WORKSPACE_DIR", str(root / "persistent-workspace"))
    monkeypatch.setenv(
        "BACKEND_CANDIDATE_ARTIFACT_MANIFEST_SHORT_5D", "models/short_5d/manifest.json"
    )
    monkeypatch.setenv(
        "BACKEND_CANDIDATE_ARTIFACT_MANIFEST_SHA256_SHORT_5D", "short-checksum"
    )
    monkeypatch.setenv(
        "BACKEND_CANDIDATE_ARTIFACT_MANIFEST_MEDIUM_20D",
        "models/medium_20d/manifest.json",
    )
    monkeypatch.setenv(
        "BACKEND_CANDIDATE_ARTIFACT_MANIFEST_SHA256_MEDIUM_20D", "medium-checksum"
    )
    configured = execution.PipelineExecutionService(service.database, service.settings)
    assert configured.workspace_dir == root / "persistent-workspace"
    assert configured.repository_root == root
    assert configured.candidate_artifact_manifest == (
        root / "persistent-workspace" / "models" / "short_5d" / "manifest.json"
    )
    assert configured.candidate_artifact_manifest_sha256 == "short-checksum"
    assert configured.medium_candidate_artifact_manifest == (
        root / "persistent-workspace" / "models" / "medium_20d" / "manifest.json"
    )
    assert configured.medium_candidate_artifact_manifest_sha256 == "medium-checksum"
