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
    assert "model_assignments" not in result
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


def test_model_date_assignment_survives_input_order_and_failed_date_only_retry():
    requests = tuple(
        pipeline.LlmBackfillRequest(date(2026, 10, day), uuid.uuid4())
        for day in (15, 16, 17, 18)
    )
    deployments = ("gpt-6.1-sol", "gpt-6-astra")
    assigned = dict(zip(
        requests, pipeline.assign_backfill_deployments(requests, deployments), strict=True,
    ))
    assert set(assigned.values()) == set(deployments)
    reversed_requests = tuple(reversed(requests))
    assert dict(zip(
        reversed_requests, pipeline.assign_backfill_deployments(reversed_requests, deployments),
        strict=True,
    )) == assigned
    for request in requests:
        assert pipeline.assign_backfill_deployments((request,), deployments) == (assigned[request],)


@pytest.mark.parametrize("deployments", [
    ("",), ("bad name",), ("../model",), ("x" * 129,),
    ("gpt-6-astra", "gpt-6-astra"), ("MODEL", "model"),
])
def test_backfill_rejects_invalid_model_routing_before_creating_clients(
    monkeypatch, tmp_path, deployments,
):
    factory = MagicMock()
    monkeypatch.setattr(pipeline, "create_llm_preselection_service", factory)
    with pytest.raises(ValueError, match="unique deployment names"):
        asyncio.run(pipeline.run_llm_backfill(
            SimpleNamespace(backfill_max_concurrency=2),
            requests=(pipeline.LlmBackfillRequest(date(2026, 10, 15), uuid.uuid4()),),
            repository_root=tmp_path, deployments=deployments,
        ))
    factory.assert_not_called()


@pytest.mark.parametrize("failed_day", [None, 16])
def test_model_backfill_shares_quota_per_model_and_keeps_date_failures_isolated(
    monkeypatch, tmp_path, failed_day,
):
    services = []
    active = peak = 0
    requests = tuple(
        pipeline.LlmBackfillRequest(date(2026, 10, day), uuid.uuid4())
        for day in (17, 15, 18, 16)
    )
    deployments = ("gpt-6.1-sol", "gpt-6-astra")
    assigned = dict(zip(
        requests, pipeline.assign_backfill_deployments(requests, deployments), strict=True,
    ))

    def factory(settings, *, repository_root, deployment):
        async def run(*, target_session, execution_context_id):
            nonlocal active, peak
            request = pipeline.LlmBackfillRequest(target_session, execution_context_id)
            assert assigned[request] == deployment
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1
            if target_session.day == failed_day:
                raise RuntimeError("provider failed")
            return LlmPreselectionSummary(
                uuid.uuid4(), uuid.uuid4(), target_session, "SUCCEEDED", 20, False,
            )
        service = SimpleNamespace(
            run=run, enricher=SimpleNamespace(rate_limiter=None),
            ranker=SimpleNamespace(
                rate_limiter=LlmRateLimiter(RateLimits(60, 250000, 4096)),
                aclose=AsyncMock(),
            ),
        )
        services.append((deployment, service))
        return service

    monkeypatch.setattr(pipeline, "create_llm_preselection_service", factory)
    result = asyncio.run(pipeline.run_llm_backfill(
        SimpleNamespace(backfill_max_concurrency=2), requests=requests,
        repository_root=tmp_path, deployments=deployments,
    ))
    assert peak == 2
    assert result["status"] == ("SUCCEEDED" if failed_day is None else "PARTIAL")
    assert [row["deployment"] for row in result["results"]] == list(assigned.values())
    assert result["model_routing_version"] == "date-ordinal-v1"
    assert result["model_assignments"] == [
        {"price_session_date": request.target_session,
         "execution_context_id": request.execution_context_id, "deployment": deployment}
        for request, deployment in assigned.items()
    ]
    pools = {}
    for deployment, service in services:
        limiter = service.ranker.rate_limiter
        assert limiter is pools.setdefault(deployment, limiter)
        assert service.enricher.rate_limiter is limiter
        assert limiter.limits.tokens_per_minute == 250000
        service.ranker.aclose.assert_awaited_once()
    assert len({id(pool) for pool in pools.values()}) == 2


def test_service_model_override_does_not_change_environment_or_default_settings(
    monkeypatch, tmp_path,
):
    from sp500_candidate_engine.llm_preselection import service
    from sp500_candidate_engine.llm_preselection.ranker import LlmRankerSettings

    original = LlmRankerSettings(
        endpoint="https://example.openai.azure.com", deployment="gpt-6.1-sol",
        api_version="2024-10-21",
    )
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", original.deployment)
    monkeypatch.setenv("FUSION_ENABLED", "false")
    monkeypatch.setattr(service.LlmRankerSettings, "from_env", lambda: original)
    monkeypatch.setattr(
        service, "load_runtime_llm_config",
        lambda root: SimpleNamespace(enrichment=None, event_policy=True),
    )
    monkeypatch.setattr(service, "Database", MagicMock())
    constructor = MagicMock()
    monkeypatch.setattr(service, "LlmPreselectionService", constructor)
    service.create_llm_preselection_service(
        MagicMock(), repository_root=tmp_path, deployment="gpt-6-astra"
    )
    assert constructor.call_args.args[2].deployment == "gpt-6-astra"
    assert original.deployment == "gpt-6.1-sol"
    assert service.os.environ["AZURE_OPENAI_DEPLOYMENT"] == "gpt-6.1-sol"
