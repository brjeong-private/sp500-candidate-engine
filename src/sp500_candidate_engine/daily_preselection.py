from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from types import SimpleNamespace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sp500_candidate_engine.fusion.service import FusionSummary
    from sp500_candidate_engine.llm_preselection.service import LlmPreselectionSummary

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ParallelPreselectionResult:
    quantitative: SimpleNamespace | None
    llm: LlmPreselectionSummary | None
    failures: dict[str, str]
    status: str
    fusion: FusionSummary | None = None
    fusion_requested: bool = False
    fusion_failure_code: str | None = None


async def run_parallel_preselections(
    *,
    quantitative_runner: Callable[[], SimpleNamespace],
    llm_runner: Callable[[], Awaitable[LlmPreselectionSummary]],
) -> ParallelPreselectionResult:
    """Join independent branches without discarding the other branch on failure."""
    failures: dict[str, str] = {}

    async def quantitative() -> SimpleNamespace | None:
        try:
            return await asyncio.to_thread(quantitative_runner)
        except Exception as error:
            logger.exception("quantitative_preselection_pipeline_failed")
            failures["quantitative"] = type(error).__name__
            return None

    async def llm() -> LlmPreselectionSummary | None:
        try:
            return await llm_runner()
        except Exception as error:
            logger.exception("llm_preselection_pipeline_failed")
            failures["llm"] = type(error).__name__
            return None

    quantitative_result, llm_result = await asyncio.gather(quantitative(), llm())
    quantitative_ok = (
        quantitative_result is not None
        and quantitative_result.candidate_count == 20
    )
    llm_ok = (
        llm_result is not None
        and llm_result.status == "SUCCEEDED"
        and llm_result.selected_count == 20
    )
    return ParallelPreselectionResult(
        quantitative=quantitative_result,
        llm=llm_result,
        failures=failures,
        status=(
            "SUCCEEDED"
            if quantitative_ok and llm_ok
            else "PARTIAL_SUCCESS"
            if quantitative_ok or llm_ok
            else "FAILED"
        ),
    )
