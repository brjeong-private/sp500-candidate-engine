from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

ORCHESTRATOR_ROOT = Path(__file__).resolve().parents[2] / "orchestrator"
sys.path.insert(0, str(ORCHESTRATOR_ROOT))

import clients  # noqa: E402
import settings  # noqa: E402
import workflow  # noqa: E402


def _settings():
    return settings.Settings(
        candidate_base_url="https://candidate.example.test",
        candidate_api_key="candidate-key",
        candidate_resource_id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Web/sites/c",
        candidate_postgres_resource_id=(
            "/subscriptions/sub/resourceGroups/rg/providers/"
            "Microsoft.DBforPostgreSQL/flexibleServers/c-db"
        ),
        candidate_postgres_public_network_access="Disabled",
        portal_base_url="https://portal.example.test",
        portal_api_key="portal-key",
        portal_resource_id="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Web/sites/p",
        portal_mysql_resource_id=(
            "/subscriptions/sub/resourceGroups/rg/providers/"
            "Microsoft.DBforMySQL/flexibleServers/p-db"
        ),
        portal_mysql_public_network_access="Disabled",
        tradingagents_base_url=None,
        tradingagents_resource_id=(
            "/subscriptions/sub/resourceGroups/rg/providers/"
            "Microsoft.App/containerApps/tradingagents"
        ),
        tradingagents_min_replicas=1,
        orchestrator_storage_resource_id=(
            "/subscriptions/sub/resourceGroups/rg/providers/"
            "Microsoft.Storage/storageAccounts/orchestrator"
        ),
        orchestrator_storage_container_name="app-package",
        orchestrator_storage_public_network_access="Disabled",
        orchestrator_storage_network_default_action="Deny",
        acs_endpoint="https://acs.communication.azure.com",
        email_sender="sender@example.test",
        email_recipients=("recipient@example.test",),
        exchange_mic="XNYS",
    )


def _candidate_items(*, status: str = "SUCCEEDED", count: int = 5):
    return [
        {
            "price_session_date": "2026-10-09",
            "status": status,
            "model_purpose": "MEDIUM_20D",
            "selected_count": count,
            "requested_count": 10,
            "position": position,
            "ticker": f"T{position}",
            "instrument_id": f"instrument-{position}",
            "selection_run_id": "selection-id",
        }
        for position in range(1, count + 1)
    ]


@pytest.mark.parametrize(
    "items",
    [
        [],
        _candidate_items(status="SHORTFALL"),
        _candidate_items(count=4),
        [
            {**item, "selection_run_id": f"selection-{item['position']}"}
            for item in _candidate_items()
        ],
        [{**item, "position": 1} for item in _candidate_items()],
    ],
)
def test_existing_gate_rejects_missing_partial_or_invalid_results(monkeypatch, items):
    monkeypatch.setattr(clients.Settings, "from_env", _settings)
    monkeypatch.setattr(
        clients,
        "request_json",
        lambda *args, **kwargs: {"items": items, "next_cursor": None},
    )

    assert (
        clients.fetch_and_verify_candidates(
            {
                "analysis_date": "2026-10-09",
                "model_purpose": "MEDIUM_20D",
                "existing_only": True,
            }
        )
        == []
    )


def test_existing_gate_queries_exact_date_and_model(monkeypatch):
    monkeypatch.setattr(clients.Settings, "from_env", _settings)
    captured = {}

    def request_json(*args, **kwargs):
        captured.update(kwargs)
        return {"items": _candidate_items(), "next_cursor": None}

    monkeypatch.setattr(clients, "request_json", request_json)

    result = clients.fetch_and_verify_candidates(
        {
            "analysis_date": "2026-10-09",
            "model_purpose": "MEDIUM_20D",
            "existing_only": True,
        }
    )

    assert len(result) == 5
    assert captured["params"]["date"] == "2026-10-09"
    assert captured["params"]["model_purpose"] == "MEDIUM_20D"


def test_submit_gate_does_not_post_when_exact_result_exists(monkeypatch):
    monkeypatch.setattr(clients.Settings, "from_env", _settings)
    methods = []

    def request_json(method, *args, **kwargs):
        methods.append(method)
        return {"items": _candidate_items(), "next_cursor": None}

    monkeypatch.setattr(clients, "request_json", request_json)

    result = clients.submit_candidate_daily(
        {"analysis_date": "2026-10-09", "model_purpose": "MEDIUM_20D"}
    )

    assert result == {
        "status": "SKIPPED_EXISTING",
        "selection_run_id": "selection-id",
        "candidate_count": 5,
    }
    assert methods == ["GET"]


def test_submit_gate_fails_closed_when_candidate_lookup_fails(monkeypatch):
    monkeypatch.setattr(clients.Settings, "from_env", _settings)

    def request_json(*args, **kwargs):
        raise clients.ExternalServiceError("candidate unavailable")

    monkeypatch.setattr(clients, "request_json", request_json)

    with pytest.raises(clients.ExternalServiceError, match="candidate unavailable"):
        clients.submit_candidate_daily(
            {"analysis_date": "2026-10-09", "model_purpose": "MEDIUM_20D"}
        )


class FakeContext:
    current_utc_datetime = datetime(2026, 10, 12, 10, 30, tzinfo=UTC)

    def get_input(self):
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


def test_orchestrator_skips_candidate_post_and_portal_for_exact_existing_result():
    activities = []

    def respond(event):
        assert event[0] == "activity"
        name, payload = event[1], event[2]
        activities.append((name, payload))
        if name == "check_exchange_session":
            return {"is_session": True, "data_complete": True}
        if name == "readiness_preflight":
            return {"status": "ready"}
        if name == "send_email":
            return {"sent": True}
        if name == "submit_candidate_daily":
            return {
                "status": "SKIPPED_EXISTING",
                "selection_run_id": "selection-id",
                "candidate_count": 5,
            }
        raise AssertionError(f"unexpected activity: {name}")

    outcome = _run(workflow.daily_orchestrator(FakeContext()), respond)

    assert outcome == {
        "state": "SKIPPED_EXISTING",
        "analysis_date": "2026-10-09",
        "model_purpose": "MEDIUM_20D",
        "selection_run_id": "selection-id",
        "candidate_count": 5,
    }
    names = [name for name, _ in activities]
    assert "candidate_run_status" not in names
    assert "submit_portal_candidate_analysis" not in names
    terminal_emails = [
        payload
        for name, payload in activities
        if name == "send_email" and "SKIPPED_EXISTING" in payload["subject"]
    ]
    assert len(terminal_emails) == 1


def test_orchestrator_submits_normally_when_existing_result_is_not_exact():
    activities = []

    def respond(event):
        assert event[0] == "activity"
        name, payload = event[1], event[2]
        activities.append((name, payload))
        if name == "check_exchange_session":
            return {"is_session": True, "data_complete": True}
        if name in {"readiness_preflight", "send_email"}:
            return {"status": "ok"}
        if name == "fetch_and_verify_candidates":
            return [
                {
                    "selection_run_id": "new-selection",
                    "ticker": f"T{position}",
                    "instrument_id": f"id-{position}",
                    "model_purpose": "MEDIUM_20D",
                    "position": position,
                }
                for position in range(1, 6)
            ]
        if name == "submit_candidate_daily":
            return {"process_run_id": "new-run", "status": "PENDING"}
        if name == "candidate_run_status":
            return {"process_run_id": "new-run", "status": "SUCCEEDED", "terminal": True}
        if name == "submit_portal_candidate_analysis":
            return {
                **payload,
                "daily_analysis_id": 1,
                "jobs": [{"status": "completed"} for _ in range(5)],
                "terminal": True,
                "succeeded": 5,
                "failed": 0,
            }
        raise AssertionError(name)

    outcome = _run(workflow.daily_orchestrator(FakeContext()), respond)

    assert outcome["state"] == "SUCCEEDED"
    names = [name for name, _ in activities]
    assert names.count("submit_candidate_daily") == 1
    assert names.count("submit_portal_candidate_analysis") == 1
