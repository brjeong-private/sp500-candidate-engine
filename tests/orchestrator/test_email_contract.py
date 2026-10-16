from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

ORCHESTRATOR_ROOT = Path(__file__).resolve().parents[2] / "orchestrator"
sys.path.insert(0, str(ORCHESTRATOR_ROOT))

import workflow  # noqa: E402


class FakeContext:
    current_utc_datetime = datetime(2026, 10, 12, 10, 30, tzinfo=UTC)

    def get_input(self) -> dict[str, Any]:
        return {
            "analysis_date": "2026-10-09",
            "model_purpose": "MEDIUM_20D",
            "candidate_timeout_minutes": 120,
            "portal_timeout_minutes": 360,
            "poll_seconds": 60,
        }

    def call_activity(self, name: str, payload: Any):
        return ("activity", name, payload)

    def create_timer(self, fire_at):
        return ("timer", fire_at)


def _run(generator, responder):
    try:
        event = next(generator)
        while True:
            if event[:2] == ("activity", "emit_pipeline_telemetry"):
                event = generator.send({"emitted": True})
                continue
            try:
                response = responder(event)
            except Exception as error:
                event = generator.throw(error)
            else:
                event = generator.send(response)
    except StopIteration as stopped:
        return stopped.value


def _candidates() -> list[dict[str, Any]]:
    return [
        {
            "ticker": f"T{position}",
            "instrument_id": f"id-{position}",
            "selection_run_id": "selection-id",
            "model_purpose": "MEDIUM_20D",
            "position": position,
        }
        for position in range(1, 21)
    ]


@pytest.mark.parametrize("email_disabled", [False, True])
def test_actual_execution_sends_exact_started_and_terminal_subjects(email_disabled):
    emails = []

    def respond(event):
        assert event[0] == "activity"
        name, payload = event[1], event[2]
        if name == "check_exchange_session":
            return {"is_session": True, "data_complete": True}
        if name == "readiness_preflight":
            return {"status": "ready", "checked": "candidate", "remediated": "none"}
        if name == "submit_candidate_daily":
            return {"process_run_id": "run-id", "status": "PENDING"}
        if name == "send_email":
            emails.append(payload)
            return {"sent": False, "disabled": True} if email_disabled else {"sent": True}
        if name == "candidate_run_status":
            return {"process_run_id": "run-id", "status": "SUCCEEDED", "terminal": True}
        if name == "fetch_and_verify_candidates":
            return _candidates()
        raise AssertionError(name)

    outcome = _run(workflow.daily_orchestrator(FakeContext()), respond)

    assert outcome["state"] == "SUCCEEDED"
    assert [email["subject"] for email in emails] == [
        "[candidate-orchestrator] MEDIUM_20D 2026-10-09 STARTED",
        "[candidate-orchestrator] MEDIUM_20D 2026-10-09 SUCCEEDED",
    ]


def test_skipped_existing_sends_only_exact_terminal_subject():
    emails = []

    def respond(event):
        name, payload = event[1], event[2]
        if name == "check_exchange_session":
            return {"is_session": True, "data_complete": True}
        if name == "readiness_preflight":
            return {"status": "ready"}
        if name == "submit_candidate_daily":
            return {
                "status": "SKIPPED_EXISTING",
                "selection_run_id": "selection-id",
                "candidate_count": 5,
            }
        if name == "send_email":
            emails.append(payload)
            return {"sent": True}
        raise AssertionError(name)

    outcome = _run(workflow.daily_orchestrator(FakeContext()), respond)

    assert outcome["state"] == "SKIPPED_EXISTING"
    assert [email["subject"] for email in emails] == [
        "[candidate-orchestrator] MEDIUM_20D 2026-10-09 SKIPPED_EXISTING"
    ]


def test_disabled_email_does_not_fail_pipeline():
    def respond(event):
        name = event[1]
        if name == "check_exchange_session":
            return {"is_session": True, "data_complete": True}
        if name == "readiness_preflight":
            return {"status": "ready"}
        if name == "submit_candidate_daily":
            return {
                "status": "SKIPPED_EXISTING",
                "selection_run_id": "selection-id",
                "candidate_count": 5,
            }
        if name == "send_email":
            return {"sent": False, "disabled": True}
        raise AssertionError(name)

    outcome = _run(workflow.daily_orchestrator(FakeContext()), respond)

    assert outcome["state"] == "SKIPPED_EXISTING"


def test_disabled_email_emits_skipped_telemetry():
    context = FakeContext()
    email = workflow._send_email(
        context,
        context.get_input(),
        {"subject": "disabled", "body": ""},
        stage="started",
    )

    assert next(email) == (
        "activity",
        "send_email",
        {"subject": "disabled", "body": ""},
    )
    telemetry = email.send({"sent": False, "disabled": True})

    assert telemetry[1] == "emit_pipeline_telemetry"
    assert telemetry[2]["state"] == "SKIPPED"


@pytest.mark.parametrize(
    ("failing_activity", "expected_stage", "expected_reason"),
    [
        ("check_exchange_session", "eligibility", "ELIGIBILITY_CHECK_FAILED"),
        ("readiness_preflight", "preflight", "PREFLIGHT_FAILED"),
        ("submit_candidate_daily", "candidate_submit", "CANDIDATE_SUBMIT_FAILED"),
        ("candidate_run_status", "candidate_poll", "CANDIDATE_POLL_FAILED"),
        ("fetch_and_verify_candidates", "candidate_fetch", "CANDIDATE_FETCH_FAILED"),
    ],
)
def test_activity_exceptions_use_limited_stage_specific_failure_codes(
    failing_activity,
    expected_stage,
    expected_reason,
):
    emails = []

    def respond(event):
        if event[0] == "timer":
            return None
        name, payload = event[1], event[2]
        if name == failing_activity:
            raise RuntimeError("secret exception detail")
        if name == "check_exchange_session":
            return {"is_session": True, "data_complete": True}
        if name == "readiness_preflight":
            return {"status": "ready"}
        if name == "submit_candidate_daily":
            return {"process_run_id": "run-id", "status": "PENDING"}
        if name == "send_email":
            emails.append(payload)
            return {"sent": True}
        if name == "candidate_run_status":
            return {"process_run_id": "run-id", "status": "SUCCEEDED", "terminal": True}
        if name == "fetch_and_verify_candidates":
            return _candidates()
        if name == "submit_portal_candidate_analysis":
            return {
                **payload,
                "daily_analysis_id": 7,
                "jobs": [{"status": "pending"} for _ in range(5)],
                "terminal": False,
                "succeeded": 0,
                "failed": 0,
            }
        raise AssertionError(name)

    outcome = _run(workflow.daily_orchestrator(FakeContext()), respond)

    assert outcome["state"] == "FAILED"
    assert outcome["stage"] == expected_stage
    assert outcome["reason"] == expected_reason
    assert emails[-1]["subject"] == ("[candidate-orchestrator] MEDIUM_20D 2026-10-09 FAILED")
    assert "secret exception detail" not in emails[-1]["body"]
    assert "RuntimeError" not in emails[-1]["body"]


def test_email_failures_return_safe_email_code_without_retrying_terminal_email():
    email_calls = 0

    def respond(event):
        nonlocal email_calls
        name = event[1]
        if name == "check_exchange_session":
            return {"is_session": True, "data_complete": True}
        if name == "readiness_preflight":
            return {"status": "ready"}
        if name == "submit_candidate_daily":
            return {
                "status": "SKIPPED_EXISTING",
                "selection_run_id": "selection-id",
                "candidate_count": 5,
            }
        if name == "send_email":
            email_calls += 1
            return {"sent": False, "error": "sensitive provider detail"}
        raise AssertionError(name)

    outcome = _run(workflow.daily_orchestrator(FakeContext()), respond)

    assert outcome["state"] == "FAILED"
    assert outcome["stage"] == "email"
    assert outcome["reason"] == "EMAIL_TERMINAL_FAILED"
    assert email_calls == 1
