import asyncio
import uuid
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from sp500_candidate_engine.llm_preselection import pipeline
from sp500_candidate_engine.llm_preselection.config import RateLimits
from sp500_candidate_engine.llm_preselection.rate_limits import LlmRateLimiter
from sp500_candidate_engine.llm_preselection.service import LlmPreselectionSummary


@pytest.mark.parametrize("fails", [False, True])
def test_standalone_pipeline_owns_client_cleanup_without_qlib(monkeypatch, fails):
    summary = object()
    run = AsyncMock(
        return_value=summary,
        side_effect=RuntimeError("ranking failed") if fails else None,
    )
    close = AsyncMock()
    factory = MagicMock(
        return_value=SimpleNamespace(run=run, ranker=SimpleNamespace(aclose=close))
    )
    monkeypatch.setattr(pipeline, "create_llm_preselection_service", factory)
    settings = MagicMock()
    context_id = uuid.uuid4()
    target = date(2026, 10, 14)
    root = Path(__file__).parents[2]

    def execute():
        return asyncio.run(
            pipeline.run_llm_preselection(
                settings,
                target_session=target,
                execution_context_id=context_id,
                repository_root=root,
            )
        )

    if fails:
        with pytest.raises(RuntimeError, match="ranking failed"):
            execute()
    else:
        assert execute() is summary
    run.assert_awaited_once_with(
        target_session=target, execution_context_id=context_id
    )
    factory.assert_called_once_with(settings, repository_root=root)
    close.assert_awaited_once()


def test_backfill_overlaps_dates_isolates_failure_and_shares_quota(monkeypatch, tmp_path):
    active = peak = 0
    services = []

    async def run(*, target_session, execution_context_id):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        if target_session.day == 15:
            raise RuntimeError("provider failed")
        return LlmPreselectionSummary(
            uuid.uuid4(), uuid.uuid4(), target_session, "SUCCEEDED", 20, False,
        )

    def factory(*args, **kwargs):
        service = SimpleNamespace(
            run=run, enricher=SimpleNamespace(rate_limiter=None),
            ranker=SimpleNamespace(
                rate_limiter=LlmRateLimiter(RateLimits(100, 1000, 10)),
                aclose=AsyncMock(),
            ),
        )
        services.append(service)
        return service

    monkeypatch.setattr(pipeline, "create_llm_preselection_service", factory)
    requests = tuple(
        pipeline.LlmBackfillRequest(date(2026, 10, day), uuid.uuid4())
        for day in (15, 16, 17)
    )
    result = asyncio.run(pipeline.run_llm_backfill(
        SimpleNamespace(backfill_max_concurrency=2),
        requests=requests, repository_root=tmp_path,
    ))
    assert peak == 2
    assert result["status"] == "PARTIAL"
    assert [row["status"] for row in result["results"]] == [
        "FAILED", "SUCCEEDED", "SUCCEEDED",
    ]
    assert [row["price_session_date"] for row in result["results"]] == [
        request.target_session for request in requests
    ]
    for service in services:
        service.ranker.aclose.assert_awaited_once()
        assert service.ranker.rate_limiter is services[0].ranker.rate_limiter
        assert service.enricher.rate_limiter is services[0].ranker.rate_limiter


@pytest.mark.parametrize("requests", [
    (),
    tuple(pipeline.LlmBackfillRequest(date(2026, 10, 15), uuid.uuid4()) for _ in range(2)),
])
def test_backfill_rejects_missing_or_duplicate_dates(requests, tmp_path):
    with pytest.raises(ValueError, match="unique"):
        asyncio.run(pipeline.run_llm_backfill(
            SimpleNamespace(backfill_max_concurrency=2),
            requests=requests, repository_root=tmp_path,
        ))


def test_backfill_client_close_failure_does_not_cancel_other_date(monkeypatch, tmp_path):
    def factory(*args, **kwargs):
        async def run(**kwargs):
            return LlmPreselectionSummary(
                uuid.uuid4(), uuid.uuid4(), kwargs["target_session"], "SUCCEEDED", 20, False,
            )
        return SimpleNamespace(
            run=run, enricher=None,
            ranker=SimpleNamespace(
                rate_limiter=None, aclose=AsyncMock(side_effect=RuntimeError("close failed")),
            ),
        )

    monkeypatch.setattr(pipeline, "create_llm_preselection_service", factory)
    result = asyncio.run(pipeline.run_llm_backfill(
        SimpleNamespace(backfill_max_concurrency=2),
        requests=(pipeline.LlmBackfillRequest(date(2026, 10, 15), uuid.uuid4()),),
        repository_root=tmp_path,
    ))
    assert result["status"] == "FAILED"
    assert result["results"][0]["failure_code"] == "RuntimeError"
