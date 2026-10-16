import asyncio
import threading
import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from sp500_candidate_engine.daily_preselection import run_parallel_preselections
from sp500_candidate_engine.llm_preselection.service import LlmPreselectionSummary


def _llm_summary(status="SUCCEEDED", count=20):
    return LlmPreselectionSummary(
        llm_ranking_run_id=uuid.uuid4(),
        selection_run_id=uuid.uuid4(),
        price_session_date=date(2026, 10, 14),
        status=status,
        selected_count=count,
        reused=False,
    )


def test_pipelines_start_concurrently_before_either_completes():
    quantitative_started = threading.Event()
    llm_started = threading.Event()
    summary = _llm_summary()

    def quantitative():
        quantitative_started.set()
        assert llm_started.wait(timeout=5)
        return SimpleNamespace(candidate_count=20)

    async def llm():
        assert await asyncio.to_thread(quantitative_started.wait, 5)
        llm_started.set()
        return summary

    result = asyncio.run(
        run_parallel_preselections(
            quantitative_runner=quantitative,
            llm_runner=llm,
        )
    )

    assert result.status == "SUCCEEDED"
    assert result.quantitative.candidate_count == 20
    assert result.llm is summary
    assert result.failures == {}


@pytest.mark.parametrize(
    ("quantitative_fails", "llm_fails", "expected"),
    [
        (True, False, "PARTIAL_SUCCESS"),
        (False, True, "PARTIAL_SUCCESS"),
        (True, True, "FAILED"),
    ],
)
def test_branch_failure_preserves_the_other_pipeline(
    quantitative_fails, llm_fails, expected, caplog
):
    summary = _llm_summary()

    def quantitative():
        if quantitative_fails:
            raise RuntimeError("quantitative artifact unavailable")
        return SimpleNamespace(candidate_count=20)

    async def llm():
        if llm_fails:
            raise TimeoutError("LLM unavailable")
        return summary

    result = asyncio.run(
        run_parallel_preselections(
            quantitative_runner=quantitative, llm_runner=llm
        )
    )

    assert result.status == expected
    assert (result.quantitative is None) == quantitative_fails
    assert (result.llm is None) == llm_fails
    if quantitative_fails:
        assert result.failures["quantitative"] == "RuntimeError"
        assert "quantitative_preselection_pipeline_failed" in caplog.text
    if llm_fails:
        assert result.failures["llm"] == "TimeoutError"
        assert "llm_preselection_pipeline_failed" in caplog.text


@pytest.mark.parametrize("branch", ["quantitative", "llm"])
def test_shortfall_is_not_reported_as_two_successful_top_20s(branch):
    async def llm():
        return _llm_summary(
            "SHORTFALL" if branch == "llm" else "SUCCEEDED",
            0 if branch == "llm" else 20,
        )

    result = asyncio.run(
        run_parallel_preselections(
            quantitative_runner=lambda: SimpleNamespace(
                candidate_count=19 if branch == "quantitative" else 20
            ),
            llm_runner=llm,
        )
    )

    assert result.status == "PARTIAL_SUCCESS"


@pytest.mark.parametrize("quantitative_fails", [False, True])
def test_daily_result_keeps_llm_as_a_sibling_not_a_quantitative_field(
    monkeypatch, quantitative_fails
):
    from sp500_candidate_engine import batch_pipeline
    from sp500_candidate_engine.daily_preselection import ParallelPreselectionResult

    target = date(2026, 10, 14)
    context_id = uuid.uuid4()
    quantitative = SimpleNamespace(
        price_session_date=target,
        model_version_id=uuid.uuid4(),
        scoring_run_id=uuid.uuid4(),
        selection_run_id=uuid.uuid4(),
        candidate_count=20,
        model_status="SHADOW",
        promotion_gate_passed=False,
        execution_context_id=context_id,
    )
    llm = _llm_summary()
    result = ParallelPreselectionResult(
        quantitative=None if quantitative_fails else quantitative,
        llm=llm,
        failures={"quantitative": "RuntimeError"} if quantitative_fails else {},
        status="PARTIAL_SUCCESS" if quantitative_fails else "SUCCEEDED",
    )
    runner = AsyncMock(return_value=result)
    tracker = MagicMock()
    tracker.__enter__.return_value = tracker
    tracker.finalize.return_value = {"status": "SUCCEEDED"}
    monkeypatch.setattr(batch_pipeline, "Database", MagicMock())
    monkeypatch.setattr(batch_pipeline, "ProcessTracker", lambda _: tracker)
    monkeypatch.setattr(batch_pipeline, "ProcessLogWriter", MagicMock())
    monkeypatch.setattr(
        batch_pipeline,
        "collect_production_inputs",
        AsyncMock(
            return_value=SimpleNamespace(
                universe_count=20,
                changed_bars=20,
                changed_actions=0,
                changed_events=0,
                missing_bars=0,
            )
        ),
    )
    legacy_runner = MagicMock(side_effect=AssertionError("Legacy runner must not execute"))

    response = asyncio.run(
        batch_pipeline.run_daily_process(
            MagicMock(),
            target_date=target,
            process_run_id=uuid.uuid4(),
            run_candidates=True,
            model_purpose="MEDIUM_20D",
            candidate_runner=legacy_runner,
            preselection_runner=runner,
        )
    )

    assert response["status"] == result.status
    assert response["llm_preselection_run"]["selection_run_id"] == llm.selection_run_id
    assert response["llm_preselection_run"]["candidate_count"] == 20
    assert response["llm_preselection_run"]["status"] == "SUCCEEDED"
    if quantitative_fails:
        assert response["candidate_run"] is None
        assert response["quantitative_preselection_status"] == "FAILED"
        assert response["preselection_failures"] == {"quantitative": "RuntimeError"}
    else:
        assert response["candidate_run"]["selection_run_id"] == quantitative.selection_run_id
        assert "llm_preselection_run_id" not in response["candidate_run"]
        assert response["quantitative_preselection_status"] == "SUCCEEDED"
    runner.assert_awaited_once()
    legacy_runner.assert_not_called()
