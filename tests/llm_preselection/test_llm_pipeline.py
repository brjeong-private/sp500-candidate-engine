import asyncio
import uuid
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from sp500_candidate_engine.llm_preselection import pipeline


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
