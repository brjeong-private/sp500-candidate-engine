import asyncio
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from backend.app.services.pipeline_execution import PipelineExecutionService
from sp500_candidate_engine.analytics.historical_export import HistoricalQlibExportService
from sp500_candidate_engine.fusion.repository import FusionRepository
from sp500_candidate_engine.fusion.service import FusionService, FusionSummary
from sp500_candidate_engine.llm_preselection.service import LlmPreselectionSummary

ROOT = Path(__file__).resolve().parents[2]
DAY = date(2026, 10, 14)
CONTEXT, QUANT, LLM, FUSION = (UUID(int=index) for index in range(2001, 2005))


@pytest.mark.parametrize("reuse_quant", [False, True])
def test_backend_runs_fusion_from_pinned_sibling_runs_and_reuses_quant(
    monkeypatch, tmp_path, reuse_quant
):
    monkeypatch.setenv("FUSION_ENABLED", "true")
    monkeypatch.setenv("LLM_PRESELECTION_ENABLED", "true")
    monkeypatch.setenv(
        "LLM_PRESELECTION_POLICY_PATH", "config/llm_preselection/policy_event_v2.yaml"
    )
    database = MagicMock()
    service = PipelineExecutionService(database, MagicMock(), workspace_dir=tmp_path)
    service.candidate_history_start = MagicMock(return_value=date(2026, 7, 1))
    context = SimpleNamespace(execution_context_id=CONTEXT, universe_version_id=UUID(int=2503))
    monkeypatch.setattr(
        HistoricalQlibExportService, "prepare_preselection_context",
        MagicMock(return_value=context),
    )
    find = MagicMock(return_value={
        "selection_run_id": QUANT, "candidate_count": 20,
        "price_session_date": DAY, "model_version_id": UUID(int=2500),
        "scoring_run_id": UUID(int=2501), "execution_context_id": CONTEXT,
    } if reuse_quant else None)
    monkeypatch.setattr(FusionRepository, "find_quantitative", find)
    inference = MagicMock(return_value=SimpleNamespace(selection_run_id=QUANT, candidate_count=20))
    monkeypatch.setattr(service, "run_candidate_inference", inference)
    llm_runner = AsyncMock(return_value=LlmPreselectionSummary(
        UUID(int=2502), LLM, DAY, "SUCCEEDED", 20, False
    ))
    monkeypatch.setattr(
        "sp500_candidate_engine.llm_preselection.pipeline.run_llm_preselection", llm_runner
    )
    fuse = MagicMock(return_value=FusionSummary(FUSION, "SUCCEEDED", 20, None, False))
    monkeypatch.setattr(FusionService, "run", fuse)
    result = asyncio.run(service.run_daily_preselections(
        target_date=DAY, process_run_id=UUID(int=2600)
    ))
    assert result.status == "SUCCEEDED" and result.fusion.fusion_run_id == FUSION
    assert result.fusion_requested
    assert inference.call_count == (0 if reuse_quant else 1)
    if not reuse_quant:
        assert inference.call_args.kwargs["input_context"] is context
    assert llm_runner.call_args.kwargs["execution_context_id"] == CONTEXT
    assert fuse.call_args.kwargs == {
        "context_id": CONTEXT, "target_session": DAY, "quant_id": QUANT, "llm_id": LLM,
    }
    assert find.call_args.kwargs["policy_hash"]
    assert find.call_args.kwargs["universe_version_id"] == context.universe_version_id


def test_legacy_llm_policy_is_not_silently_used_for_fusion(monkeypatch, tmp_path):
    from sp500_candidate_engine.llm_preselection.service import create_llm_preselection_service

    monkeypatch.setenv("FUSION_ENABLED", "true")
    monkeypatch.setenv("LLM_PRESELECTION_POLICY_PATH", "config/llm_preselection/policy_v1.yaml")
    with pytest.raises(ValueError, match="event LLM policy"):
        create_llm_preselection_service(MagicMock(), repository_root=ROOT)


def test_disabled_fusion_does_not_start_new_stage(monkeypatch, tmp_path):
    monkeypatch.setenv("FUSION_ENABLED", "false")
    database = MagicMock()
    service = PipelineExecutionService(database, MagicMock(), workspace_dir=tmp_path)
    monkeypatch.setattr(service, "candidate_history_start", lambda _: date(2026, 7, 1))
    monkeypatch.setattr(
        HistoricalQlibExportService, "prepare_preselection_context",
        lambda *args, **kwargs: SimpleNamespace(execution_context_id=CONTEXT),
    )
    monkeypatch.setattr(
        service, "run_candidate_inference",
        lambda *args, **kwargs: SimpleNamespace(selection_run_id=QUANT, candidate_count=20),
    )
    monkeypatch.setattr(
        "sp500_candidate_engine.llm_preselection.pipeline.run_llm_preselection",
        AsyncMock(return_value=LlmPreselectionSummary(
            UUID(int=2502), LLM, DAY, "SUCCEEDED", 20, False
        )),
    )
    fusion = MagicMock()
    monkeypatch.setattr(FusionService, "run", fusion)
    result = asyncio.run(service.run_daily_preselections(
        target_date=DAY, process_run_id=UUID(int=2600)
    ))
    assert result.status == "SUCCEEDED" and not result.fusion_requested
    fusion.assert_not_called()


def test_migration_022_preserves_count_bounds_and_replaces_old_success_check():
    sql = (ROOT / "sql" / "022_llm_preselection.sql").read_text(encoding="utf-8")
    assert "DROP CONSTRAINT IF EXISTS selection_run_check1" in sql
    assert "DROP CONSTRAINT IF EXISTS selection_run_success_count_check" in sql
    assert "CHECK (selected_count BETWEEN 0 AND requested_count)" in sql
    assert "requested_count = 20 AND selected_count = 20" in sql
    assert "requested_count BETWEEN 5 AND 10" in sql
    assert "selected_count BETWEEN 5 AND requested_count" in sql
