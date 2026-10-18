import json
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from backend.app.services import candidate_stages
from sp500_candidate_engine import cli
from sp500_candidate_engine.llm_preselection import pipeline as llm_pipeline

RUN = UUID(int=1000)


@pytest.mark.parametrize("value", ["bad", "2026-10-15=bad", "2026-13-15=" + str(RUN)])
def test_llm_backfill_cli_rejects_malformed_pairs(value, capsys):
    with pytest.raises(SystemExit) as error:
        cli.build_parser().parse_args(["backfill-llm-candidates", "--session-context", value])
    assert error.value.code == 2
    assert "Expected YYYY-MM-DD=UUID" in capsys.readouterr().err


@pytest.mark.parametrize("status", ["SUCCEEDED", "PARTIAL", "FAILED"])
def test_llm_backfill_cli_reports_all_results_before_non_success_exit(
    monkeypatch, capsys, status,
):
    monkeypatch.setattr(cli.Settings, "from_env", lambda _: MagicMock())
    runner = AsyncMock(return_value={"status": status, "results": []})
    monkeypatch.setattr(llm_pipeline, "run_llm_backfill", runner)
    monkeypatch.setattr(sys, "argv", [
        "candidate-engine", "backfill-llm-candidates",
        "--session-context", f"2026-10-15={RUN}",
        "--session-context", f"2026-10-16={UUID(int=1001)}",
    ])
    if status == "SUCCEEDED":
        cli.main()
    else:
        with pytest.raises(SystemExit) as error:
            cli.main()
        assert error.value.code == 1
    assert json.loads(capsys.readouterr().out)["status"] == status
    assert runner.await_args.kwargs["requests"] == (
        llm_pipeline.LlmBackfillRequest(cli._date("2026-10-15"), RUN),
        llm_pipeline.LlmBackfillRequest(cli._date("2026-10-16"), UUID(int=1001)),
    )
    assert runner.await_args.kwargs["deployments"] == ()


def test_llm_backfill_cli_passes_explicit_model_deployments(monkeypatch, capsys):
    monkeypatch.setattr(cli.Settings, "from_env", lambda _: MagicMock())
    runner = AsyncMock(return_value={"status": "SUCCEEDED", "results": []})
    monkeypatch.setattr(llm_pipeline, "run_llm_backfill", runner)
    monkeypatch.setattr(sys, "argv", [
        "candidate-engine", "backfill-llm-candidates",
        "--session-context", f"2026-10-15={RUN}",
        "--model-deployment", "gpt-6.1-sol", "--model-deployment", "gpt-6-astra",
    ])
    cli.main()
    assert json.loads(capsys.readouterr().out)["status"] == "SUCCEEDED"
    assert runner.await_args.kwargs["deployments"] == ("gpt-6.1-sol", "gpt-6-astra")


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
