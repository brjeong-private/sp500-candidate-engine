from __future__ import annotations

import asyncio
import logging
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


async def run_llm_backfill(
    settings: Settings, *, requests: tuple[LlmBackfillRequest, ...], repository_root: Path,
) -> dict[str, object]:
    """Evaluate pinned dates independently; report failures without cancelling siblings."""
    if not requests or len({request.target_session for request in requests}) != len(requests):
        raise ValueError("LLM backfill requires nonempty, unique session/context pairs")
    if type(settings.backfill_max_concurrency) is not int or not (
        1 <= settings.backfill_max_concurrency <= 8
    ):
        raise ValueError("Backfill concurrency must be between 1 and 8")
    semaphore = asyncio.Semaphore(settings.backfill_max_concurrency)
    shared_limiter: LlmRateLimiter | None = None

    async def one(request: LlmBackfillRequest) -> dict[str, object]:
        nonlocal shared_limiter
        async with semaphore:
            service = None
            try:
                service = create_llm_preselection_service(settings, repository_root=repository_root)
                try:
                    if shared_limiter is None:
                        shared_limiter = service.ranker.rate_limiter
                    service.ranker.rate_limiter = shared_limiter
                    if service.enricher is not None:
                        service.enricher.rate_limiter = shared_limiter
                    summary = await service.run(
                        target_session=request.target_session,
                        execution_context_id=request.execution_context_id,
                    )
                finally:
                    await service.ranker.aclose()
                return asdict(summary)
            except Exception as error:
                logger.exception(
                    "llm_backfill_date_failed",
                    extra={"target_session": request.target_session.isoformat(),
                           "failure_code": type(error).__name__},
                )
                return {
                    "price_session_date": request.target_session,
                    "execution_context_id": request.execution_context_id,
                    "status": "FAILED", "failure_code": type(error).__name__,
                }

    results = await asyncio.gather(*(one(request) for request in requests))
    successes = sum(result["status"] == "SUCCEEDED" for result in results)
    return {
        "status": (
            "SUCCEEDED" if successes == len(results) else "PARTIAL" if successes else "FAILED"
        ),
        "max_concurrency": settings.backfill_max_concurrency, "results": results,
    }


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
