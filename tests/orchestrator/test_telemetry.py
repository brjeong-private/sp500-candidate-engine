from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ORCHESTRATOR_ROOT = Path(__file__).resolve().parents[2] / "orchestrator"
sys.path.insert(0, str(ORCHESTRATOR_ROOT))

import guardian  # noqa: E402
import telemetry  # noqa: E402
import workflow  # noqa: E402


class RecordingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


class ModelContext:
    instance_id = "candidate-daily-2026-10-09-medium_20d"
    current_utc_datetime = datetime(2026, 10, 12, 10, 30, tzinfo=UTC)

    def get_input(self) -> dict[str, Any]:
        return {
            "analysis_date": "2026-10-09",
            "model_purpose": "MEDIUM_20D",
            "parent_instance_id": "candidate-dual-2026-10-09",
            "candidate_timeout_minutes": 120,
            "portal_timeout_minutes": 360,
            "poll_seconds": 60,
        }

    def call_activity(self, name: str, payload: Any):
        return ("activity", name, payload)

    def create_timer(self, fire_at):
        return ("timer", fire_at)


def _run_model(*, email_sent: bool = True) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    emitted: list[dict[str, Any]] = []
    generator = workflow.daily_orchestrator(ModelContext())
    try:
        event = next(generator)
        while True:
            name, payload = event[1], event[2]
            if name == "emit_pipeline_telemetry":
                emitted.append(payload)
                response = {"emitted": True}
            elif name == "check_exchange_session":
                response = {"is_session": True, "data_complete": True}
            elif name == "readiness_preflight":
                response = {"status": "ready", "remediated": "none"}
            elif name == "submit_candidate_daily":
                response = {
                    "status": "SKIPPED_EXISTING",
                    "selection_run_id": "selection-7",
                    "candidate_count": 7,
                }
            elif name == "send_email":
                response = {"sent": email_sent}
            else:
                raise AssertionError(name)
            event = generator.send(response)
    except StopIteration as stopped:
        return stopped.value, emitted


def test_model_telemetry_is_activity_based_and_correlated():
    outcome, emitted = _run_model()

    assert outcome["state"] == "SKIPPED_EXISTING"
    assert [item["event"] for item in emitted] == [
        "pipeline.model.started",
        "pipeline.model.skipped_existing",
        "pipeline.email.terminal",
        "pipeline.model.terminal",
    ]
    terminal = emitted[-1]
    assert terminal == {
        "event": "pipeline.model.terminal",
        "parent_instance_id": "candidate-dual-2026-10-09",
        "model_instance_id": "candidate-daily-2026-10-09-medium_20d",
        "target_session": "2026-10-09",
        "model_purpose": "MEDIUM_20D",
        "candidate_process_run_id": None,
        "selection_run_id": "selection-7",
        "daily_analysis_id": None,
        "state": "SKIPPED_EXISTING",
        "stage": "terminal",
        "remediated": False,
    }


def test_emitter_drops_secrets_payloads_and_report_content():
    logger = logging.Logger("test.pipeline.telemetry")
    handler = RecordingHandler()
    logger.addHandler(handler)

    emitted = telemetry.emit_pipeline_telemetry(
        {
            "event": "pipeline.model.terminal",
            "state": "SUCCEEDED",
            "stage": "terminal",
            "target_session": "2026-10-09",
            "secret": "do-not-log",
            "payload": {"raw": "do-not-log"},
            "report_body": "do-not-log",
        },
        logger=logger,
    )

    logged = json.loads(handler.messages[0])
    assert logged == emitted
    assert logged["target_session"] == "2026-10-09"
    assert set(logged) == {"event", "stage", "state", "target_session", "timestamp"}
    assert "do-not-log" not in handler.messages[0]


def test_email_failure_is_emitted_without_provider_detail():
    outcome, emitted = _run_model(email_sent=False)

    assert outcome["state"] == "FAILED"
    email = next(item for item in emitted if item["event"] == "pipeline.email.terminal")
    assert email["state"] == "FAILED"
    assert email["stage"] == "terminal"
    assert set(email).issubset(telemetry.SAFE_FIELDS)


def test_guardian_emits_start_remediation_and_terminal_events():
    emitted: list[dict[str, Any]] = []

    result = guardian.run_guardian(
        preflight=lambda: {
            "status": "ready",
            "checked": "candidate",
            "remediated": "candidate_app:start",
        },
        telemetry=lambda payload: emitted.append(payload) or payload,
    )

    assert result["state"] == "SUCCEEDED"
    assert [item["event"] for item in emitted] == [
        "pipeline.guardian.started",
        "pipeline.guardian.remediation",
        "pipeline.guardian.terminal",
    ]
    assert emitted[-1]["remediated"] is True
