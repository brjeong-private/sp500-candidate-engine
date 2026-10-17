import asyncio
import copy
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app.repositories.candidate_stage_runs import CandidateStageConflict
from backend.app.routers.candidate_stages import get_stage_service, router
from backend.app.schemas.candidate_stages import CandidateStageRequest, CandidateStageResult
from backend.app.services.candidate_stages import CandidateStageService, StageContractChanged
from sp500_candidate_engine.cli import build_parser


class Cursor:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def fetchone(self):
        return copy.deepcopy(self.rows[0]) if self.rows else None

    def fetchall(self):
        return copy.deepcopy(self.rows)


class MemoryDatabase:
    def __init__(self):
        self.rows = {}
        self.lock = threading.RLock()

    @contextmanager
    def connect(self, **kwargs):
        yield self

    @contextmanager
    def transaction(self):
        with self.lock:
            before = copy.deepcopy(self.rows)
            try:
                yield self
            except BaseException:
                self.rows = before
                raise

    def execute(self, sql, params=()):
        statement = " ".join(sql.split())
        assert sql.count("%s") == len(params)
        if statement.startswith("SELECT pg_advisory"):
            return Cursor()
        if statement.startswith("SELECT process_run_id FROM ops.backend_pipeline_request"):
            return Cursor()
        if "WHERE idempotency_key=%s" in statement:
            return Cursor([row for row in self.rows.values()
                           if row["idempotency_key"] == params[0]])
        if "SELECT *" in statement and "WHERE stage_run_id=%s" in statement:
            return Cursor([self.rows[params[0]]] if params[0] in self.rows else [])
        if "SELECT stage_run_id" in statement and "WHERE input_hash=%s" in statement:
            return Cursor([row for row in self.rows.values()
                           if row["input_hash"] == params[0]
                           and row["status"] in {"PENDING", "RUNNING"}])
        if statement.startswith("INSERT INTO"):
            names = (
                "stage_run_id", "stage", "target_session", "execution_context_id", "model_purpose",
                "request_payload", "request_hash", "contract", "contract_hash", "input_hash",
                "idempotency_key", "retry_of_run_id", "owner",
            )
            values = [item.obj if hasattr(item, "obj") else item for item in params]
            row = dict(zip(names, values, strict=True))
            row.update(
                created_at=datetime.now(UTC), started_at=None, finished_at=None,
                status="PENDING", failure_code=None, result=None,
            )
            self.rows[row["stage_run_id"]] = row
            return Cursor([row])
        if "SET status='RUNNING'" in statement:
            row = self.rows.get(params[0])
            if row is None or row["status"] != "PENDING":
                return Cursor()
            row.update(status="RUNNING", started_at=datetime.now(UTC))
            return Cursor([row])
        if "SET status=%s" in statement:
            status, result, failure, run_id = params
            row = self.rows.get(run_id)
            if row is None or row["status"] != "RUNNING":
                return Cursor()
            row.update(
                status=status, result=result.obj if result is not None else None,
                failure_code=failure, finished_at=datetime.now(UTC),
            )
            return Cursor([row])
        if "failure_code='INTERRUPTED'" in statement:
            rows = []
            for row in self.rows.values():
                if row["owner"] == "API" and row["status"] in {"PENDING", "RUNNING"}:
                    row.update(
                        status="FAILED", failure_code="INTERRUPTED", finished_at=datetime.now(UTC)
                    )
                    rows.append(row)
            return Cursor(rows)
        raise AssertionError("Unexpected stage SQL: " + statement)


def request(stage="QUANTITATIVE", **kwargs):
    data = {
        "stage": stage, "target_session": date(2026, 10, 15),
        "execution_context_id": UUID(int=1000), **kwargs,
    }
    if stage == "FUSION":
        data.update(quant_selection_run_id=UUID(int=1001), llm_preselection_run_id=UUID(int=1002))
    return CandidateStageRequest.model_validate(data)


@pytest.fixture
def service(monkeypatch):
    service = CandidateStageService(MemoryDatabase(), MagicMock())
    monkeypatch.setattr(
        service, "capture_contract", MagicMock(return_value={"context": {"hash": "fixed"}})
    )
    monkeypatch.setattr(service, "_run", AsyncMock(return_value=(
        CandidateStageResult(selection_run_id=UUID(int=2000), candidate_count=20, reused=False),
        "SUCCEEDED", None,
    )))
    return service


@pytest.mark.parametrize("payload", [
    {"stage": "FUSION"}, {"stage": "FUSION", "model_purpose": "SHORT_5D"},
    {"stage": "LLM_PRESELECTION", "model_purpose": "MEDIUM_20D"},
    {"stage": "QUANTITATIVE", "quant_selection_run_id": str(UUID(int=1))},
    {"stage": "UNKNOWN"}, {"stage": "QUANTITATIVE", "raw_payload": "forbidden"},
])
def test_invalid_stage_surface_is_rejected(payload):
    with pytest.raises(ValidationError):
        CandidateStageRequest.model_validate({
            "target_session": "2026-10-15", "execution_context_id": str(UUID(int=1000)), **payload,
        })


def test_defaults_preserve_model_purpose_and_source_boundaries():
    assert request().model_purpose == "MEDIUM_20D"
    assert request("QUANTITATIVE", model_purpose="SHORT_5D").model_purpose == "SHORT_5D"
    assert request("LLM_PRESELECTION").model_purpose is None
    assert request("FUSION").model_purpose == "MEDIUM_20D"


def test_key_replay_and_stored_result_are_separate_ids(service):
    accepted = service.accept(request(), "stage-test")
    assert accepted.status == "PENDING"
    replay = service.accept(request(), "stage-test")
    assert replay._is_replay and replay.stage_run_id == accepted.stage_run_id
    asyncio.run(service.execute(accepted.stage_run_id))
    state = service.get(accepted.stage_run_id)
    assert state.status == "SUCCEEDED"
    assert state.result.selection_run_id == UUID(int=2000)
    assert state.stage_run_id != state.result.selection_run_id
    assert service.accept(request(), "stage-test").status == "SUCCEEDED"
    with pytest.raises(CandidateStageConflict):
        service.accept(request("LLM_PRESELECTION"), "stage-test")


def test_concurrent_same_input_creates_only_one_request(service):
    def accept(index):
        try:
            return service.accept(request(), f"stage-{index}")
        except CandidateStageConflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(accept, range(2)))
    assert sum(row is not None for row in rows) == 1
    assert len(service.database.rows) == 1


def test_execute_claims_once_and_never_changes_terminal_state(service):
    accepted = service.accept(request(), "once")
    asyncio.run(service.execute(accepted.stage_run_id))
    with pytest.raises(CandidateStageConflict):
        asyncio.run(service.execute(accepted.stage_run_id))
    assert service.get(accepted.stage_run_id).status == "SUCCEEDED"
    service._run.assert_awaited_once()


def test_failure_is_logged_and_explicit_retry_preserves_original(service, caplog):
    service._run.side_effect = TimeoutError("simulated")
    original = service.accept(request("LLM_PRESELECTION"), "failed")
    with pytest.raises(TimeoutError):
        asyncio.run(service.execute(original.stage_run_id))
    failed = service.get(original.stage_run_id)
    assert failed.status == "FAILED" and failed.failure_code == "TimeoutError"
    assert "candidate_stage_failed" in caplog.text
    retry = service.retry(original.stage_run_id, "explicit-retry")
    assert retry.stage_run_id != original.stage_run_id
    assert service.get(retry.stage_run_id).retry_of_run_id == original.stage_run_id
    assert service.get(retry.stage_run_id).contract_hash == failed.contract_hash
    assert service.retry(original.stage_run_id, "explicit-retry")._is_replay


def test_changed_contract_blocks_retry_or_fails_claimed_run(service):
    accepted = service.accept(request(), "original")
    service.capture_contract.return_value = {"context": {"hash": "changed"}}
    with pytest.raises(StageContractChanged):
        asyncio.run(service.execute(accepted.stage_run_id))
    assert service.get(accepted.stage_run_id).failure_code == "CONTRACT_CHANGED"
    with pytest.raises(CandidateStageConflict, match="contract changed"):
        service.retry(accepted.stage_run_id, "changed-retry")
    service._run.assert_not_awaited()


def test_shortfall_is_not_success_and_can_be_retried(service):
    service._run.return_value = (
        CandidateStageResult(fusion_run_id=UUID(int=2001), candidate_count=19, reused=False),
        "SHORTFALL", "INSUFFICIENT_UNION_CANDIDATES",
    )
    original = service.accept(request("FUSION"), "shortfall")
    asyncio.run(service.execute(original.stage_run_id))
    assert service.get(original.stage_run_id).status == "SHORTFALL"
    assert service.get(original.stage_run_id).result.candidate_count == 19
    assert service.retry(original.stage_run_id, "retry-shortfall").status == "PENDING"


def test_successful_and_pending_stages_cannot_be_retried(service):
    accepted = service.accept(request(), "success")
    with pytest.raises(CandidateStageConflict, match="failed/shortfall"):
        service.retry(accepted.stage_run_id, "retry-pending")
    asyncio.run(service.execute(accepted.stage_run_id))
    with pytest.raises(CandidateStageConflict, match="failed/shortfall"):
        service.retry(accepted.stage_run_id, "retry-success")


def test_api_restart_reconciles_only_owned_nonterminal_requests(service):
    first = service.accept(request(), "api-owned")
    service.owner = "CLI"
    second = service.accept(request("LLM_PRESELECTION"), "cli-owned")
    assert service.reconcile_interrupted() == 1
    assert service.get(first.stage_run_id).failure_code == "INTERRUPTED"
    assert service.get(second.stage_run_id).status == "PENDING"
    assert service.reconcile_interrupted() == 0


def test_fake_nineteen_item_success_is_failure_not_success_fallback(service):
    service._run.return_value = (
        CandidateStageResult(selection_run_id=UUID(int=2000), candidate_count=19, reused=False),
        "SUCCEEDED", None,
    )
    accepted = service.accept(request(), "invalid-success")
    with pytest.raises(ValueError, match="invalid terminal"):
        asyncio.run(service.execute(accepted.stage_run_id))
    assert service.get(accepted.stage_run_id).status == "FAILED"
    assert service.get(accepted.stage_run_id).result is None


def test_llm_only_executes_llm_and_closes_its_client_without_quant(monkeypatch):
    from sp500_candidate_engine.llm_preselection import service as llm_service

    runner = AsyncMock(return_value=SimpleNamespace(
        selection_run_id=UUID(int=2200), llm_ranking_run_id=UUID(int=2201),
        selected_count=20, reused=True, status="SUCCEEDED", failure_code=None,
    ))
    close = AsyncMock()
    factory = MagicMock(return_value=SimpleNamespace(
        run=runner, ranker=SimpleNamespace(aclose=close),
    ))
    monkeypatch.setattr(llm_service, "LlmPreselectionService", factory)
    monkeypatch.setattr(llm_service, "load_runtime_llm_config", MagicMock())
    monkeypatch.setattr(
        "sp500_candidate_engine.llm_preselection.ranker.LlmRankerSettings.from_env", MagicMock()
    )
    standalone = CandidateStageService(MagicMock(), MagicMock())
    quant = MagicMock(side_effect=AssertionError("LLM must not initialize Quant"))
    monkeypatch.setattr(standalone, "_quantitative", quant)
    result, status, error = asyncio.run(standalone._run(request("LLM_PRESELECTION"), {}))
    assert status == "SUCCEEDED" and error is None
    assert result.selection_run_id == UUID(int=2200)
    runner.assert_awaited_once_with(
        target_session=date(2026, 10, 15), execution_context_id=UUID(int=1000),
    )
    close.assert_awaited_once()
    quant.assert_not_called()


def test_fusion_only_uses_explicit_source_ids_without_calling_llm(monkeypatch):
    from sp500_candidate_engine.fusion.service import FusionService
    from sp500_candidate_engine.llm_preselection import service as llm_service

    standalone = CandidateStageService(MagicMock(), MagicMock())
    monkeypatch.setattr(
        "sp500_candidate_engine.fusion.config.load_fusion_policy", MagicMock()
    )
    monkeypatch.setattr(llm_service, "load_runtime_llm_config", MagicMock())
    llm_factory = MagicMock(side_effect=AssertionError("Fusion must not call the LLM"))
    monkeypatch.setattr(llm_service, "LlmPreselectionService", llm_factory)
    fuse = MagicMock(return_value=SimpleNamespace(
        fusion_run_id=UUID(int=2300), selected_count=20, reused=True,
        status="SUCCEEDED", failure_code=None,
    ))
    monkeypatch.setattr(FusionService, "run", fuse)
    quant = MagicMock(side_effect=AssertionError("Fusion must not run Quant"))
    monkeypatch.setattr(standalone, "_quantitative", quant)
    result, status, error = asyncio.run(standalone._run(request("FUSION"), {}))
    assert status == "SUCCEEDED" and result.fusion_run_id == UUID(int=2300)
    assert result.reused and error is None
    assert fuse.call_args.kwargs == {
        "context_id": UUID(int=1000), "target_session": date(2026, 10, 15),
        "quant_id": UUID(int=1001), "llm_id": UUID(int=1002),
    }
    llm_factory.assert_not_called()
    quant.assert_not_called()


def test_quant_only_uses_pinned_artifact_and_frozen_context(monkeypatch, tmp_path):
    from backend.app.services.model_artifacts import ModelArtifactLoader
    from sp500_candidate_engine.backfill import backfill_cutoff
    from sp500_candidate_engine.fusion.repository import FusionRepository

    artifact = SimpleNamespace(manifest=SimpleNamespace(model_version_id=UUID(int=2400)))
    monkeypatch.setattr(ModelArtifactLoader, "load", lambda *args: artifact)
    monkeypatch.setattr(FusionRepository, "find_quantitative", lambda *args, **kwargs: None)
    inference = MagicMock(return_value=SimpleNamespace(
        selection_run_id=UUID(int=2401), scoring_run_id=UUID(int=2402),
        model_version_id=UUID(int=2400), candidate_count=20,
    ))
    execution = SimpleNamespace(workspace_dir=tmp_path, run_candidate_inference=inference)
    standalone = CandidateStageService(MemoryDatabase(), MagicMock(), execution=execution)
    contract = {
        "artifact": {
            "artifact_uri": "file:///fixture/manifest.json", "artifact_hash": "a" * 64,
            "model_version_id": str(UUID(int=2400)),
        },
        "context": {"universe_version_id": str(UUID(int=2500))},
    }
    result, status, error = standalone._run_quantitative(request(), contract)
    assert status == "SUCCEEDED" and error is None and result.candidate_count == 20
    assert inference.call_args.kwargs["artifact_override"] is artifact
    assert inference.call_args.kwargs["input_context"].execution_context_id == UUID(int=1000)
    assert inference.call_args.kwargs["input_context"].cutoff_at == backfill_cutoff(
        date(2026, 10, 15)
    )
    assert "process_run_id" not in inference.call_args.kwargs


def test_quant_contract_does_not_reselect_active_assignment_on_retry(monkeypatch):
    standalone = CandidateStageService(MagicMock(), MagicMock())
    monkeypatch.setattr(standalone, "_context", lambda _: {"hash": "frozen"})
    select_artifact = MagicMock(side_effect=AssertionError("Cannot select the latest assignment"))
    monkeypatch.setattr(standalone, "_artifact_reference", select_artifact)
    pinned = {"artifact": {"model_version_id": str(UUID(int=2400)), "artifact_hash": "a" * 64}}
    contract = standalone.capture_contract(request(), pinned=pinned)
    assert contract["artifact"] == pinned["artifact"]
    select_artifact.assert_not_called()


def test_standalone_legacy_llm_contract_is_not_gated_by_fusion_or_quant(monkeypatch):
    monkeypatch.setenv("LLM_PRESELECTION_ENABLED", "true")
    monkeypatch.setenv("LLM_PRESELECTION_POLICY_PATH", "config/llm_preselection/policy_v1.yaml")
    monkeypatch.setenv("FUSION_ENABLED", "true")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "explicit-llm-model")
    monkeypatch.setenv("AZURE_OPENAI_API_VERSION", "test-version")
    standalone = CandidateStageService(MagicMock(), MagicMock())
    monkeypatch.setattr(standalone, "_context", lambda _: {"hash": "frozen"})
    select_quant = MagicMock(side_effect=AssertionError("LLM does not select Quant artifacts"))
    monkeypatch.setattr(standalone, "_artifact_reference", select_quant)
    contract = standalone.capture_contract(request("LLM_PRESELECTION"))
    assert contract["llm_policy"]["policy_version"] == "daily-llm-preselection:1"
    assert contract["deployment"]["deployment"] == "explicit-llm-model"
    assert "artifact" not in contract and "fusion" not in contract
    select_quant.assert_not_called()


def test_collecting_pipeline_blocks_stage_acceptance(service, monkeypatch):
    original = service.database.execute

    def execute(sql, params=()):
        if "SELECT process_run_id FROM ops.backend_pipeline_request" in sql:
            return Cursor([{"process_run_id": UUID(int=2600)}])
        return original(sql, params)

    monkeypatch.setattr(service.database, "execute", execute)
    with pytest.raises(CandidateStageConflict, match="Collection/daily"):
        service.accept(request(), "blocked-by-collection")
    assert not service.database.rows


def test_cancelled_stage_persists_interrupted_and_can_be_retried(service):
    service._run.side_effect = asyncio.CancelledError()
    accepted = service.accept(request(), "cancelled")
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(service.execute(accepted.stage_run_id))
    assert service.get(accepted.stage_run_id).failure_code == "INTERRUPTED"
    assert service.retry(accepted.stage_run_id, "retry-cancelled").status == "PENDING"


def test_stage_api_auth_replay_and_read_preserve_safe_contract(service, monkeypatch):
    app = FastAPI()
    app.state.database = service.database
    app.state.backend_settings = SimpleNamespace(api_key="stage-test-key")
    app.include_router(router)
    app.dependency_overrides[get_stage_service] = lambda: service
    execute = MagicMock()
    monkeypatch.setattr(service, "execute_background", execute)
    headers = {"X-API-Key": "stage-test-key", "Idempotency-Key": "http-stage"}
    payload = request().model_dump(mode="json")
    with TestClient(app) as client:
        assert client.post("/api/v1/candidate-stage-runs", json=payload).status_code == 401
        response = client.post("/api/v1/candidate-stage-runs", json=payload, headers=headers)
        assert response.status_code == 202
        run_id = response.json()["stage_run_id"]
        assert client.post(
            "/api/v1/candidate-stage-runs", json=payload, headers=headers
        ).status_code == 202
        execute.assert_called_once()
        result = client.get(
            f"/api/v1/candidate-stage-runs/{run_id}", headers={"X-API-Key": "stage-test-key"}
        )
        assert result.status_code == 200 and result.json()["status"] == "PENDING"
        assert "contract" not in result.json() and "idempotency_key" not in result.json()
        assert client.get(
            f"/api/v1/candidate-stage-runs/{UUID(int=999)}", headers=headers
        ).status_code == 404
        assert client.post(
            f"/api/v1/candidate-stage-runs/{run_id}/retry",
            headers={**headers, "Idempotency-Key": "new-retry"},
        ).status_code == 409


def test_cli_exposes_only_explicit_stage_inputs():
    parser = build_parser()
    args = parser.parse_args([
        "run-stage", "--stage", "FUSION", "--date", "2026-10-15",
        "--execution-context-id", str(UUID(int=1000)), "--idempotency-key", "cli-stage",
        "--quant-selection-run-id", str(UUID(int=1001)),
        "--llm-preselection-run-id", str(UUID(int=1002)),
    ])
    assert args.stage == "FUSION" and args.model_purpose is None
    assert args.execution_context_id == UUID(int=1000)
    assert parser.parse_args(["show-stage", "--stage-run-id", str(UUID(int=1000))]).command \
        == "show-stage"
