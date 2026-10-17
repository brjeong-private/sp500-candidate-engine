from __future__ import annotations

import asyncio
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

ORCHESTRATOR_ROOT = Path(__file__).resolve().parents[2] / "orchestrator"
sys.path.insert(0, str(ORCHESTRATOR_ROOT))

import function_app  # noqa: E402
import scheduler  # noqa: E402
import workflow  # noqa: E402


class ParentContext:
    instance_id = "candidate-dual-2026-10-09"

    def get_input(self) -> dict[str, Any]:
        return {
            "analysis_date": "2026-10-09",
            "candidate_timeout_minutes": 120,
            "portal_timeout_minutes": 360,
            "poll_seconds": 60,
            "child_instance_ids": {
                "SHORT_5D": "candidate-daily-2026-10-09-short_5d",
                "MEDIUM_20D": "candidate-daily-2026-10-09-medium_20d",
            },
        }

    def call_sub_orchestrator(self, name: str, payload: dict[str, Any], instance_id: str):
        return ("sub_orchestrator", name, payload, instance_id)

    def call_activity(self, name: str, payload: dict[str, Any]):
        return ("activity", name, payload)


def _run(generator, responses):
    events = []
    try:
        event = next(generator)
        while True:
            if event[:2] == ("activity", "emit_pipeline_telemetry"):
                event = generator.send({"emitted": True})
                continue
            events.append(event)
            event = generator.send(next(responses))
    except StopIteration as stopped:
        return stopped.value, events


def _child_result(state: str, model_purpose: str, **details: Any) -> dict[str, Any]:
    return {
        "state": state,
        "analysis_date": "2026-10-09",
        "model_purpose": model_purpose,
        **details,
    }


def test_parent_runs_short_then_medium_and_returns_child_ids():
    outcome, events = _run(
        workflow.dual_model_parent(ParentContext()),
        iter(
            [
                _child_result("PARTIAL_FAILED", "SHORT_5D", stage="portal"),
                _child_result("SKIPPED_EXISTING", "MEDIUM_20D"),
            ]
        ),
    )

    assert [event[2]["model_purpose"] for event in events] == ["SHORT_5D", "MEDIUM_20D"]
    assert [event[3] for event in events] == [
        "candidate-daily-2026-10-09-short_5d",
        "candidate-daily-2026-10-09-medium_20d",
    ]
    assert outcome["state"] == "PARTIAL_FAILED"
    assert outcome["models"]["SHORT_5D"]["state"] == "PARTIAL_FAILED"
    assert outcome["models"]["MEDIUM_20D"]["state"] == "SKIPPED_EXISTING"


def test_parent_stops_after_short_core_failure():
    outcome, events = _run(
        workflow.dual_model_parent(ParentContext()),
        iter([_child_result("FAILED", "SHORT_5D", stage="candidate")]),
    )

    assert len(events) == 1
    assert outcome["state"] == "FAILED"
    assert outcome["stopped_after"] == "SHORT_5D"
    assert outcome["models"]["MEDIUM_20D"] == {
        "instance_id": "candidate-daily-2026-10-09-medium_20d",
        "state": "NOT_STARTED",
        "reason": "short_core_failure",
    }


def test_parent_stops_for_all_short_candidate_core_stages():
    for stage in ("eligibility", "candidate_submit", "candidate_poll", "candidate_fetch"):
        outcome, events = _run(
            workflow.dual_model_parent(ParentContext()),
            iter([_child_result("FAILED", "SHORT_5D", stage=stage)]),
        )

        assert len(events) == 1
        assert outcome["state"] == "FAILED"
        assert outcome["stopped_after"] == "SHORT_5D"
        assert outcome["models"]["MEDIUM_20D"]["state"] == "NOT_STARTED"


def test_parent_stops_after_short_preflight_timeout():
    outcome, events = _run(
        workflow.dual_model_parent(ParentContext()),
        iter([_child_result("TIMED_OUT", "SHORT_5D", stage="preflight")]),
    )

    assert len(events) == 1
    assert outcome["state"] == "TIMED_OUT"
    assert outcome["models"]["MEDIUM_20D"]["state"] == "NOT_STARTED"


def test_parent_continues_after_short_skipped_existing():
    outcome, events = _run(
        workflow.dual_model_parent(ParentContext()),
        iter(
            [
                _child_result("SKIPPED_EXISTING", "SHORT_5D"),
                _child_result("SUCCEEDED", "MEDIUM_20D"),
            ]
        ),
    )

    assert len(events) == 2
    assert outcome["state"] == "SUCCEEDED"
    assert outcome["models"]["SHORT_5D"]["state"] == "SKIPPED_EXISTING"
    assert outcome["models"]["MEDIUM_20D"]["state"] == "SUCCEEDED"


def test_parent_continues_after_short_portal_timeout():
    outcome, events = _run(
        workflow.dual_model_parent(ParentContext()),
        iter(
            [
                _child_result("TIMED_OUT", "SHORT_5D", stage="portal"),
                _child_result("SUCCEEDED", "MEDIUM_20D"),
            ]
        ),
    )

    assert len(events) == 2
    assert outcome["state"] == "TIMED_OUT"
    assert outcome["models"]["MEDIUM_20D"]["state"] == "SUCCEEDED"


class TimerClient:
    def __init__(self, existing=None):
        self.existing = existing
        self.started = []

    async def get_status(self, instance_id):
        return self.existing

    async def start_new(self, name, instance_id, client_input):
        self.started.append((name, instance_id, client_input))


def test_timer_starts_only_deterministic_medium_daily_instance(monkeypatch):
    monkeypatch.setenv("FUSION_ENABLED", "true")
    monkeypatch.setenv("FUSION_EXTERNAL_DELIVERY_ENABLED", "true")
    monkeypatch.setattr(function_app, "scheduled_analysis_date", lambda _now: date(2026, 10, 9))
    monkeypatch.setattr(function_app, "scheduled_weekly_iso_week", lambda _now: None)
    client = TimerClient()

    asyncio.run(function_app._hourly_timer(client))

    assert len(client.started) == 1
    name, instance_id, daily_input = client.started[0]
    assert name == "daily_orchestrator"
    assert instance_id == "candidate-daily-2026-10-09-medium_20d"
    assert daily_input["model_purpose"] == "MEDIUM_20D"
    assert daily_input["analysis_date"] == "2026-10-09"
    assert daily_input["fusion_enabled"] is True
    assert daily_input["fusion_external_delivery_enabled"] is True
    version, config_hash = function_app.fusion_policy_identity()
    assert daily_input["fusion_policy_version"] == version
    assert daily_input["fusion_config_hash"] == config_hash
    assert "child_instance_ids" not in daily_input


@pytest.mark.parametrize("fusion_enabled", [None, "false", "invalid"])
def test_timer_rejects_non_fusion_configuration(monkeypatch, fusion_enabled):
    monkeypatch.setattr(function_app, "scheduled_analysis_date", lambda _now: date(2026, 10, 19))
    monkeypatch.setattr(function_app, "scheduled_weekly_iso_week", lambda _now: None)
    monkeypatch.delenv("FUSION_ENABLED", raising=False)
    monkeypatch.setenv("FUSION_EXTERNAL_DELIVERY_ENABLED", "false")
    if fusion_enabled is not None:
        monkeypatch.setenv("FUSION_ENABLED", fusion_enabled)
    client = TimerClient()

    with pytest.raises(function_app.ConfigurationError, match="FUSION_ENABLED"):
        asyncio.run(function_app._hourly_timer(client))

    assert client.started == []


def test_timer_fusion_does_not_implicitly_enable_external_delivery(monkeypatch):
    monkeypatch.setattr(function_app, "scheduled_analysis_date", lambda _now: date(2026, 10, 19))
    monkeypatch.setattr(function_app, "scheduled_weekly_iso_week", lambda _now: None)
    monkeypatch.setenv("FUSION_ENABLED", "true")
    monkeypatch.setenv("FUSION_EXTERNAL_DELIVERY_ENABLED", "false")
    client = TimerClient()

    asyncio.run(function_app._hourly_timer(client))

    assert client.started[0][2]["fusion_enabled"] is True
    assert client.started[0][2]["fusion_external_delivery_enabled"] is False


def test_timer_restarts_terminal_medium_instance(monkeypatch):
    monkeypatch.setenv("FUSION_ENABLED", "true")
    monkeypatch.setattr(function_app, "scheduled_analysis_date", lambda _now: date(2026, 10, 9))
    monkeypatch.setattr(function_app, "scheduled_weekly_iso_week", lambda _now: None)
    client = TimerClient(existing={"runtime_status": "Completed"})

    asyncio.run(function_app._hourly_timer(client))

    assert len(client.started) == 1
    assert client.started[0][1] == "candidate-daily-2026-10-09-medium_20d"


def test_timer_does_not_restart_active_medium_instance(monkeypatch):
    monkeypatch.setattr(function_app, "scheduled_analysis_date", lambda _now: date(2026, 10, 9))
    monkeypatch.setattr(function_app, "scheduled_weekly_iso_week", lambda _now: None)
    client = TimerClient(existing={"runtime_status": "Running"})

    asyncio.run(function_app._hourly_timer(client))

    assert client.started == []


def test_timer_checks_medium_instance_after_terminal_legacy_parent(monkeypatch):
    monkeypatch.setattr(function_app, "scheduled_analysis_date", lambda _now: date(2026, 10, 9))
    monkeypatch.setattr(function_app, "scheduled_weekly_iso_week", lambda _now: None)
    client = TimerClient()
    checked = []

    async def get_status(instance_id):
        checked.append(instance_id)
        return {"runtime_status": "Running" if instance_id.endswith("medium_20d") else "Completed"}

    client.get_status = get_status
    asyncio.run(function_app._hourly_timer(client))

    assert checked == [
        "candidate-dual-2026-10-09",
        "candidate-daily-2026-10-09-medium_20d",
    ]
    assert client.started == []


def test_timer_preserves_active_legacy_parent_without_starting_medium(monkeypatch):
    monkeypatch.setattr(function_app, "scheduled_analysis_date", lambda _now: date(2026, 10, 9))
    monkeypatch.setattr(function_app, "scheduled_weekly_iso_week", lambda _now: None)
    client = TimerClient()
    checked = []

    async def get_status(instance_id):
        checked.append(instance_id)
        return {"runtime_status": "Running"}

    client.get_status = get_status
    asyncio.run(function_app._hourly_timer(client))

    assert checked == ["candidate-dual-2026-10-09"]
    assert client.started == []


def test_parent_instance_id_is_deterministic():
    assert scheduler.parent_orchestration_instance_id(date(2026, 10, 9)) == (
        "candidate-dual-2026-10-09"
    )


def test_timer_gate_remains_0530_new_york():
    assert scheduler.scheduled_analysis_date(datetime(2026, 7, 12, 9, 30, tzinfo=UTC)) == date(
        2026, 7, 11
    )
    assert scheduler.scheduled_analysis_date(datetime(2026, 7, 12, 9, 45, tzinfo=UTC)) is None


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime(2026, 10, 19, 9, 30, tzinfo=UTC), date(2026, 10, 18)),
        (datetime(2026, 10, 20, 9, 30, tzinfo=UTC), date(2026, 10, 19)),
    ],
)
def test_october_fusion_check_dates_preserve_previous_calendar_day(now, expected):
    assert scheduler.scheduled_analysis_date(now) == expected
