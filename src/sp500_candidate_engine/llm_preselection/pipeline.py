from __future__ import annotations

import asyncio
import logging
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from sp500_candidate_engine.config import Settings
from sp500_candidate_engine.llm_preselection.rate_limits import LlmRateLimiter
from sp500_candidate_engine.llm_preselection.service import (
    LlmPreselectionSummary,
    create_llm_preselection_service,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LlmBackfillRequest:
    target_session: date
    execution_context_id: uuid.UUID


def assign_backfill_deployments(
    requests: tuple[LlmBackfillRequest, ...], deployments: tuple[str, ...],
) -> tuple[str | None, ...]:
    if any(
        not isinstance(value, str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value) is None
        for value in deployments
    ) or len({value.casefold() for value in deployments}) != len(deployments):
        raise ValueError("Backfill deployments must be valid, unique deployment names")
    # Calendar-based routing survives reordered inputs and failed-date-only retries.
    return tuple(
        deployments[request.target_session.toordinal() % len(deployments)] if deployments else None
        for request in requests
    )


async def run_llm_backfill(
    settings: Settings, *, requests: tuple[LlmBackfillRequest, ...], repository_root: Path,
    deployments: tuple[str, ...] = (),
) -> dict[str, object]:
    """Evaluate pinned dates independently; report failures without cancelling siblings."""
    if not requests or len({request.target_session for request in requests}) != len(requests):
        raise ValueError("LLM backfill requires nonempty, unique session/context pairs")
    if type(settings.backfill_max_concurrency) is not int or not (
        1 <= settings.backfill_max_concurrency <= 8
    ):
        raise ValueError("Backfill concurrency must be between 1 and 8")
    assignments = assign_backfill_deployments(requests, deployments)
    semaphore = asyncio.Semaphore(settings.backfill_max_concurrency)
    shared_limiters: dict[str | None, LlmRateLimiter | None] = {}

    async def one(request: LlmBackfillRequest, deployment: str | None) -> dict[str, object]:
        async with semaphore:
            service = None
            try:
                if deployment is None:
                    service = create_llm_preselection_service(
                        settings, repository_root=repository_root
                    )
                else:
                    service = create_llm_preselection_service(
                        settings, repository_root=repository_root, deployment=deployment
                    )
                try:
                    if shared_limiters.get(deployment) is None:
                        shared_limiters[deployment] = service.ranker.rate_limiter
                    shared_limiter = shared_limiters[deployment]
                    if deployment is not None and shared_limiter is None:
                        raise ValueError("Explicit model backfill requires a rate limiter")
                    service.ranker.rate_limiter = shared_limiter
                    if service.enricher is not None:
                        service.enricher.rate_limiter = shared_limiter
                    summary = await service.run(
                        target_session=request.target_session,
                        execution_context_id=request.execution_context_id,
                    )
                finally:
                    await service.ranker.aclose()
                result = asdict(summary)
                if deployment is not None:
                    result["deployment"] = deployment
                return result
            except Exception as error:
                logger.exception(
                    "llm_backfill_date_failed",
                    extra={"target_session": request.target_session.isoformat(),
                           "failure_code": type(error).__name__},
                )
                result: dict[str, object] = {
                    "price_session_date": request.target_session,
                    "execution_context_id": request.execution_context_id,
                    "status": "FAILED", "failure_code": type(error).__name__,
                }
                if deployment is not None:
                    result["deployment"] = deployment
                return result

    results = await asyncio.gather(*(
        one(request, deployment) for request, deployment in zip(requests, assignments, strict=True)
    ))
    successes = sum(result["status"] == "SUCCEEDED" for result in results)
    result = {
        "status": (
            "SUCCEEDED" if successes == len(results) else "PARTIAL" if successes else "FAILED"
        ),
        "max_concurrency": settings.backfill_max_concurrency, "results": results,
    }
    if deployments:
        result["model_routing_version"] = "date-ordinal-v1"
        result["deployments"] = list(deployments)
        result["model_assignments"] = [
            {
                "price_session_date": request.target_session,
                "execution_context_id": request.execution_context_id,
                "deployment": deployment,
            }
            for request, deployment in zip(requests, assignments, strict=True)
        ]
    return result


async def run_llm_preselection(
    settings: Settings,
    *,
    target_session: date,
    execution_context_id: uuid.UUID,
    repository_root: Path,
) -> LlmPreselectionSummary:
    """Run evidence ranking independently of Qlib artifacts and inference."""
    service = create_llm_preselection_service(
        settings, repository_root=repository_root
    )
    try:
        return await service.run(
            target_session=target_session,
            execution_context_id=execution_context_id,
        )
    finally:
        await service.ranker.aclose()
