import json
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from backend.app.services import candidate_stages
from sp500_candidate_engine import cli

RUN = UUID(int=1000)


@pytest.mark.parametrize("command", ["run-stage", "show-stage", "retry-stage"])
def test_stage_cli_delegates_to_shared_service_and_reports_result(
    monkeypatch, capsys, command
):
    settings = MagicMock()
    monkeypatch.setattr(cli.Settings, "from_env", lambda _: settings)
    database = MagicMock()
    monkeypatch.setattr(cli, "Database", lambda _: database)
    accepted = SimpleNamespace(stage_run_id=RUN, _is_replay=False)
    terminal = SimpleNamespace(
        status="SUCCEEDED",
        model_dump_json=lambda **kwargs: json.dumps({
            "stage_run_id": str(RUN), "status": "SUCCEEDED",
        }),
    )
    execute = AsyncMock()
    service = SimpleNamespace(
        accept=MagicMock(return_value=accepted), retry=MagicMock(return_value=accepted),
        get=MagicMock(return_value=terminal), execute=execute,
    )
    factory = MagicMock(return_value=service)
    monkeypatch.setattr(candidate_stages, "CandidateStageService", factory)
    arguments = ["candidate-engine", command]
    if command == "run-stage":
        arguments.extend([
            "--stage", "FUSION", "--date", "2026-10-15",
            "--execution-context-id", str(UUID(int=1001)),
            "--quant-selection-run-id", str(UUID(int=1002)),
            "--llm-preselection-run-id", str(UUID(int=1003)),
            "--idempotency-key", "cli-run-stage",
        ])
    else:
        arguments.extend(["--stage-run-id", str(RUN)])
        if command == "retry-stage":
            arguments.extend(["--idempotency-key", "cli-retry-stage"])
    monkeypatch.setattr(sys, "argv", arguments)
    cli.main()
    factory.assert_called_once_with(database, settings, owner="CLI")
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "SUCCEEDED" and result["stage_run_id"] == str(RUN)
    if command == "show-stage":
        execute.assert_not_awaited()
        service.accept.assert_not_called()
        service.retry.assert_not_called()
    else:
        execute.assert_awaited_once_with(RUN)
        if command == "run-stage":
            request = service.accept.call_args.args[0]
            assert request.stage == "FUSION"
            assert request.quant_selection_run_id == UUID(int=1002)
            assert request.llm_preselection_run_id == UUID(int=1003)
        else:
            service.retry.assert_called_once_with(RUN, "cli-retry-stage")
