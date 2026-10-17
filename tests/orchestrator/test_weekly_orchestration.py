from __future__ import annotations

import asyncio
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ORCHESTRATOR_ROOT = Path(__file__).resolve().parents[2] / "orchestrator"
sys.path.insert(0, str(ORCHESTRATOR_ROOT))

import clients  # noqa: E402
import function_app  # noqa: E402
import pytest  # noqa: E402
import scheduler  # noqa: E402
import workflow  # noqa: E402


class ParentContext:
    instance_id = "candidate-weekly-2026-W42"

    def get_input(self) -> dict[str, Any]:
        return {
            "iso_week": "2026-W42",
            "timeout_minutes": 720,
            "poll_seconds": 60,
            "child_instance_ids": {
                purpose: scheduler.weekly_model_instance_id("2026-W42", purpose)
                for purpose in ("SHORT_5D", "MEDIUM_20D")
            },
        }

    def call_activity(self, name, payload):
        return ("activity", name, payload)

    def call_sub_orchestrator(self, name, payload, instance_id):
        return ("sub", name, payload, instance_id)


def _run(generator, responses):
    events = []
    try:
        event = next(generator)
        while True:
            events.append(event)
            event = generator.send(next(responses))
    except StopIteration as stopped:
        return stopped.value, events


def test_weekly_parent_runs_both_models_after_short_failure():
    outcome, events = _run(
        workflow.weekly_parent_orchestrator(ParentContext()),
        iter(
            [
                {"eligible": True},
                {"state": "FAILED", "model_purpose": "SHORT_5D"},
                {"state": "SUCCEEDED", "model_purpose": "MEDIUM_20D"},
            ]
        ),
    )
    subevents = [event for event in events if event[0] == "sub"]
    assert [event[2]["model_purpose"] for event in subevents] == [
        "SHORT_5D",
        "MEDIUM_20D",
    ]
    assert outcome["models"]["MEDIUM_20D"]["state"] == "SUCCEEDED"


@pytest.mark.parametrize("email_result", [
    {"sent": True}, {"sent": False, "disabled": True}, {"sent": False, "error": "ProviderError"},
])
def test_weekly_notifications_report_progress_and_results_without_blocking_models(email_result):
    class Context(ParentContext):
        def get_input(self):
            return {**super().get_input(), "weekly_email_notifications": True}

    context = Context()
    events = []
    generator = workflow.weekly_parent_orchestrator(context)
    try:
        event = next(generator)
        while True:
            events.append(event)
            if event[:2] == ("activity", "weekly_eligibility"):
                response = {"eligible": True}
            elif event[:2] == ("activity", "send_email"):
                response = email_result
            elif event[:2] == ("activity", "emit_pipeline_telemetry"):
                response = {"emitted": True}
            else:
                assert event[0] == "sub"
                purpose = event[2]["model_purpose"]
                response = {
                    "state": "FAILED" if purpose == "SHORT_5D" else "SUCCEEDED",
                    "model_purpose": purpose,
                    "weekly_run_id": f"run-{purpose}",
                    "challenger_model_version_id": f"challenger-{purpose}",
                    "champion_model_version_id": f"champion-{purpose}",
                }
            event = generator.send(response)
    except StopIteration as stopped:
        outcome = stopped.value

    assert [event[2]["model_purpose"] for event in events if event[0] == "sub"] == [
        "SHORT_5D", "MEDIUM_20D",
    ]
    assert outcome["state"] == "FAILED"
    assert outcome["models"]["MEDIUM_20D"]["state"] == "SUCCEEDED"
    expected_status = "SENT" if email_result.get("sent") else (
        "DISABLED" if email_result.get("disabled") else "FAILED"
    )
    assert outcome["email_status"] == expected_status
    emails = [event[2] for event in events if event[:2] == ("activity", "send_email")]
    assert len(emails) == 4
    assert {email["category"] for email in emails} == {"weekly_training"}
    assert emails[0]["subject"].endswith("STARTED")
    assert emails[1]["subject"].endswith("SHORT_5D FAILED")
    assert emails[2]["subject"].endswith("MEDIUM_20D SUCCEEDED")
    assert emails[3]["subject"].endswith("FAILED")
    assert "challenger-MEDIUM_20D" in emails[-1]["body"]
    assert "champion-MEDIUM_20D" in emails[-1]["body"]
    assert "프로젝트: S&P 500 Candidate Engine" in emails[-1]["body"]


def test_ineligible_weekly_parent_does_not_send_email():
    class Context(ParentContext):
        def get_input(self):
            return {**super().get_input(), "weekly_email_notifications": True}

    outcome, events = _run(
        workflow.weekly_parent_orchestrator(Context()),
        iter([{"eligible": False, "reason": "ALREADY_ACCEPTED"}]),
    )
    assert outcome["state"] == "SKIPPED"
    assert [event[1] for event in events] == ["weekly_eligibility"]


def test_new_weekly_input_enables_notifications_without_changing_existing_history():
    assert function_app._weekly_parent_input("2026-W42")["weekly_email_notifications"] is True
    assert "weekly_email_notifications" not in ParentContext().get_input()


def test_weekly_model_summary_includes_stored_versions_after_activation():
    class Context(ParentContext):
        current_utc_datetime = datetime(2026, 10, 17, 4, tzinfo=UTC)

        def get_input(self):
            return {
                **super().get_input(), "model_purpose": "MEDIUM_20D",
            }

    outcome, events = _run(
        workflow.weekly_model_orchestrator(Context()),
        iter([
            {"weekly_run_id": "weekly-id", "status": "PENDING"},
            {"execution_name": "execution-id"},
            {"terminal": True, "succeeded": True},
            {
                "status": "PROMOTED", "anchor_session": "2026-10-16",
                "challenger_model_version_id": "challenger-id",
                "champion_model_version_id": "incumbent-id",
                "unexpected_provider_payload": "must-not-leak",
            },
            {"passed": True},
        ]),
    )
    assert outcome["state"] == "SUCCEEDED"
    assert outcome["challenger_model_version_id"] == "challenger-id"
    assert outcome["champion_model_version_id"] == "incumbent-id"
    assert "unexpected_provider_payload" not in outcome


def test_weekly_ids_and_new_york_weekend_gate_are_deterministic():
    assert scheduler.scheduled_weekly_iso_week(
        datetime(2026, 10, 17, 4, tzinfo=UTC)
    ) == "2026-W42"
    assert scheduler.scheduled_weekly_iso_week(
        datetime(2026, 10, 16, 23, tzinfo=UTC)
    ) is None
    assert scheduler.weekly_parent_instance_id("2026-W42") == "candidate-weekly-2026-W42"
    assert scheduler.weekly_model_instance_id("2026-W42", "SHORT_5D") == (
        "candidate-weekly-2026-W42-SHORT_5D"
    )


class TimerClient:
    def __init__(self):
        self.started = []

    async def get_status(self, _instance_id):
        return None

    async def start_new(self, name, instance_id, payload):
        self.started.append((name, instance_id, payload))


def test_hourly_weekend_gate_starts_weekly_parent(monkeypatch):
    monkeypatch.setattr(function_app, "scheduled_weekly_iso_week", lambda _now: "2026-W42")
    monkeypatch.setattr(function_app, "scheduled_analysis_date", lambda _now: None)
    client = TimerClient()
    asyncio.run(function_app._hourly_timer(client))
    assert client.started[0][0:2] == (
        "weekly_parent_orchestrator",
        "candidate-weekly-2026-W42",
    )


def test_hourly_weekend_gate_restarts_terminal_weekly_parent(monkeypatch):
    monkeypatch.setattr(function_app, "scheduled_weekly_iso_week", lambda _now: "2026-W42")
    monkeypatch.setattr(function_app, "scheduled_analysis_date", lambda _now: None)
    client = TimerClient()

    async def completed(_instance_id):
        return SimpleNamespace(runtime_status="Completed")

    client.get_status = completed
    asyncio.run(function_app._hourly_timer(client))

    assert client.started[0][0:2] == (
        "weekly_parent_orchestrator",
        "candidate-weekly-2026-W42",
    )


def test_weekend_daily_tick_keeps_weekly_models_but_starts_only_medium_daily(monkeypatch):
    monkeypatch.setenv("FUSION_ENABLED", "true")
    monkeypatch.setattr(function_app, "scheduled_weekly_iso_week", lambda _now: "2026-W42")
    monkeypatch.setattr(function_app, "scheduled_analysis_date", lambda _now: date(2026, 10, 16))
    client = TimerClient()

    asyncio.run(function_app._hourly_timer(client))

    assert [item[0] for item in client.started] == [
        "weekly_parent_orchestrator",
        "daily_orchestrator",
    ]
    assert set(client.started[0][2]["child_instance_ids"]) == {"SHORT_5D", "MEDIUM_20D"}
    assert client.started[1][2]["model_purpose"] == "MEDIUM_20D"
    assert client.started[1][2]["fusion_enabled"] is True


def test_weekly_job_template_preserves_runtime_contract_and_overrides_inputs():
    resource = {
        "properties": {
            "template": {
                "containers": [
                    {
                        "name": "candidate-training",
                        "image": "registry.example.test/candidate-training:latest",
                        "resources": {"cpu": 2.0, "memory": "4Gi"},
                        "env": [
                            {"name": "PGHOST", "value": "private.example.test"},
                            {"name": "WEEKLY_RUN_ID", "value": "stale"},
                        ],
                    }
                ],
                "volumes": [],
            }
        }
    }

    template = clients._weekly_job_template(
        resource,
        weekly_run_id="fb623c5d-323d-5986-b547-3348a00a8db5",
        model_purpose="SHORT_5D",
    )

    container = template["containers"][0]
    assert container["image"] == "registry.example.test/candidate-training:latest"
    assert container["resources"] == {"cpu": 2.0, "memory": "4Gi"}
    assert "volumes" not in template
    assert container["env"] == [
        {"name": "PGHOST", "value": "private.example.test"},
        {
            "name": "WEEKLY_RUN_ID",
            "value": "fb623c5d-323d-5986-b547-3348a00a8db5",
        },
        {"name": "MODEL_PURPOSE", "value": "SHORT_5D"},
    ]
    assert resource["properties"]["template"]["containers"][0]["env"][-1] == {
        "name": "WEEKLY_RUN_ID",
        "value": "stale",
    }


def test_weekly_job_start_posts_execution_template_at_request_root(monkeypatch):
    resource_id = (
        "/subscriptions/00000000-0000-0000-0000-000000000000/"
        "resourceGroups/test/providers/Microsoft.App/jobs/candidate-training"
    )
    resource = {
        "properties": {
            "template": {
                "containers": [
                    {
                        "name": "candidate-training",
                        "image": "registry.example.test/candidate-training:latest",
                        "resources": {"cpu": 2.0, "memory": "4Gi"},
                        "env": [],
                    }
                ]
            }
        }
    }
    credential = SimpleNamespace(get_token=lambda _scope: SimpleNamespace(token="token"))
    captured = []
    monkeypatch.setenv("CANDIDATE_TRAINING_JOB_RESOURCE_ID", resource_id)
    monkeypatch.setitem(
        sys.modules,
        "azure.identity",
        SimpleNamespace(DefaultAzureCredential=lambda: credential),
    )
    monkeypatch.setattr(
        clients.Settings,
        "from_env",
        lambda: SimpleNamespace(
            candidate_base_url="https://candidate.example.test",
            candidate_api_key="test-key",
        ),
    )
    monkeypatch.setattr(clients, "_arm_resource", lambda *_args: resource)

    def fake_request(method, url, **kwargs):
        captured.append({"method": method, "url": url, **kwargs})
        if url.endswith("/execution"):
            return {"container_job_execution_name": "execution-1"}
        return {"name": "execution-1"}

    monkeypatch.setattr(clients, "request_json", fake_request)

    result = clients.start_weekly_training_job(
        {
            "weekly_run_id": "fb623c5d-323d-5986-b547-3348a00a8db5",
            "model_purpose": "SHORT_5D",
        }
    )

    assert result == {"execution_name": "execution-1"}
    assert "template" not in captured[0]["json_body"]
    assert captured[0]["json_body"]["containers"][0]["image"].endswith(":latest")
    assert captured[1]["json_body"] == {"execution_name": "execution-1"}
