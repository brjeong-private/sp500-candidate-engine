from __future__ import annotations

import uuid
from datetime import date
from pathlib import Path

from sp500_candidate_engine.config import Settings
from sp500_candidate_engine.llm_preselection.service import (
    LlmPreselectionSummary,
    create_llm_preselection_service,
)


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
