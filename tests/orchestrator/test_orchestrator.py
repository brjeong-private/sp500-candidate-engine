from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

ORCHESTRATOR_ROOT = Path(__file__).resolve().parents[2] / "orchestrator"
INFRA_ROOT = Path(__file__).resolve().parents[2] / "infra"
sys.path.insert(0, str(ORCHESTRATOR_ROOT))

import clients  # noqa: E402
import scheduler  # noqa: E402
import settings  # noqa: E402
import workflow  # noqa: E402


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime(2026, 1, 12, 10, 30, tzinfo=UTC), "2026-01-11"),
        (datetime(2026, 7, 12, 9, 30, tzinfo=UTC), "2026-07-11"),
        (datetime(2026, 7, 12, 10, 30, tzinfo=UTC), None),
    ],
)
def test_new_york_gate_handles_standard_and_daylight_time(now, expected):
    actual = scheduler.scheduled_analysis_date(now)
    assert (actual.isoformat() if actual else None) == expected


def test_instance_id_is_deterministic():
    analysis_date = scheduler.scheduled_analysis_date(datetime(2026, 1, 12, 10, 30, tzinfo=UTC))
    assert scheduler.orchestration_instance_id(analysis_date) == "candidate-daily-2026-01-11"


@pytest.mark.parametrize(
    "value",
    [
        "http://example.test",
        "https://user:password@example.test",
        "https://example.test/path#fragment",
    ],
)
def test_outbound_url_rejects_unsafe_values(value):
    with pytest.raises(clients.ExternalServiceError):
        clients._validate_https_url(value)


def test_response_limit_uses_declared_length():
    response = httpx.Response(
        200,
        headers={"Content-Length": str(clients.MAX_RESPONSE_BYTES + 1)},
        content=b"{}",
    )
    with pytest.raises(clients.ExternalServiceError, match="size limit"):
        clients._read_limited_json(response)


def test_candidate_verification_requires_all_five_to_ten(monkeypatch):
    configured = settings.Settings(
        candidate_base_url="https://candidate.example.test",
        candidate_api_key="candidate-key",
        candidate_resource_id=(
            "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Web/sites/candidate"
        ),
        portal_base_url="https://portal.example.test",
        portal_api_key="portal-key",
        portal_resource_id=(
            "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Web/sites/portal"
        ),
        tradingagents_base_url=None,
        acs_endpoint="https://acs.communication.azure.com",
        email_sender="configured-at-runtime",
        email_recipients=("configured-at-runtime",),
        exchange_mic="XNYS",
        model_purpose="MEDIUM_20D",
    )
    monkeypatch.setattr(clients.Settings, "from_env", lambda: configured)
    items = [
        {
            "price_session_date": "2026-10-09",
            "status": "SUCCEEDED",
            "model_purpose": "MEDIUM_20D",
            "selected_count": 10,
            "requested_count": 10,
            "position": position,
            "ticker": f"T{position}",
            "instrument_id": f"instrument-{position}",
            "selection_run_id": "selection",
        }
        for position in range(1, 11)
    ]
    monkeypatch.setattr(
        clients,
        "request_json",
        lambda *args, **kwargs: {"items": items, "next_cursor": None},
    )
    result = clients.fetch_and_verify_candidates("2026-10-09")
    assert len(result) == 10
    assert [item["position"] for item in result] == list(range(1, 11))
    assert {item["model_purpose"] for item in result} == {"MEDIUM_20D"}


def _settings(*, tradingagents_base_url=None):
    return settings.Settings(
        candidate_base_url="https://candidate.example.test",
        candidate_api_key="candidate-key",
        candidate_resource_id=(
            "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Web/sites/candidate"
        ),
        portal_base_url="https://portal.example.test",
        portal_api_key="portal-token",
        portal_resource_id=(
            "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Web/sites/portal"
        ),
        tradingagents_base_url=tradingagents_base_url,
        acs_endpoint="https://acs.communication.azure.com",
        email_sender="configured-at-runtime",
        email_recipients=("configured-at-runtime",),
        exchange_mic="XNYS",
        model_purpose="MEDIUM_20D",
    )


def test_portal_batch_contract_uses_bearer_and_preserves_jobs(monkeypatch):
    monkeypatch.setattr(clients.Settings, "from_env", _settings)
    captured = {}
    jobs = [
        {
            "status": "completed" if position < 4 else "failed",
            "decision": "BUY" if position < 4 else None,
            "has_result": position < 4,
            "error": None if position < 4 else "analysis_failed",
        }
        for position in range(5)
    ]

    def fake_request(method, url, **kwargs):
        captured.update(method=method, url=url, **kwargs)
        return {
            "daily_analysis_id": 42,
            "analysis_date": "2026-10-09",
            "selection_run_id": "selection-id",
            "model_purpose": "MEDIUM_20D",
            "jobs": jobs,
        }

    monkeypatch.setattr(clients, "request_json", fake_request)
    aggregate = clients.submit_portal_candidate_analysis(
        {
            "analysis_date": "2026-10-09",
            "selection_run_id": "selection-id",
            "model_purpose": "MEDIUM_20D",
            "candidate_count": 5,
        }
    )

    assert captured["method"] == "POST"
    assert captured["url"].endswith("/api/automation/candidate-analyses")
    assert captured["headers"]["Authorization"] == "Bearer portal-token"
    assert "X-Automation-Key" not in captured["headers"]
    assert captured["json_body"] == {
        "analysis_date": "2026-10-09",
        "selection_run_id": "selection-id",
        "model_purpose": "MEDIUM_20D",
    }
    assert aggregate["jobs"] == jobs
    assert aggregate["succeeded"] == 4
    assert aggregate["failed"] == 1
    assert aggregate["terminal"] is True


def test_preflight_requires_portal_and_configured_tradingagents_ready(monkeypatch):
    configured = _settings(tradingagents_base_url="https://tradingagents.example.test")
    monkeypatch.setattr(clients.Settings, "from_env", lambda: configured)
    monkeypatch.setattr(
        clients,
        "_arm_site",
        lambda resource_id, credential: {"properties": {"state": "Running"}},
    )
    urls = []

    def fake_request(method, url, **kwargs):
        urls.append(url)
        if url.endswith("/health/ready"):
            return {"status": "ready"}
        if url.endswith("/readyz"):
            return {"status": "ready"}
        raise AssertionError(url)

    monkeypatch.setattr(clients, "request_json", fake_request)
    result = clients.readiness_preflight()

    assert result == {"status": "ready", "checked": "candidate,portal,tradingagents"}
    assert "https://portal.example.test/readyz" in urls
    assert "https://tradingagents.example.test/readyz" in urls


def test_bicep_requires_and_configures_tradingagents_url():
    template = (INFRA_ROOT / "orchestrator.bicep").read_text(encoding="utf-8")
    assert "param tradingAgentsApiUrl string\n" in template
    assert "param tradingAgentsApiUrl string =" not in template
    assert "name: 'TRADINGAGENTS_API_URL'" in template
    assert "value: tradingAgentsApiUrl" in template


class FakeContext:
    def __init__(self):
        self.current_utc_datetime = datetime(2026, 10, 12, 10, 30, tzinfo=UTC)

    def get_input(self):
        return {
            "analysis_date": "2026-10-09",
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
            try:
                response = responder(event)
            except Exception as error:
                event = generator.throw(error)
            else:
                event = generator.send(response)
    except StopIteration as stopped:
        return stopped.value


def test_portal_batch_partial_failure_is_preserved_without_stock_retries():
    candidates = [
        {
            "ticker": f"T{position}",
            "instrument_id": f"id-{position}",
            "selection_run_id": "selection-id",
            "model_purpose": "MEDIUM_20D",
            "position": position,
        }
        for position in range(1, 6)
    ]
    submissions = 0
    polls = 0

    def respond(event):
        nonlocal submissions, polls
        if event[0] == "timer":
            return None
        assert event[0] == "activity"
        name, payload = event[1], event[2]
        if name == "check_exchange_session":
            return {"is_session": True}
        if name in {"readiness_preflight", "send_email"}:
            return {"status": "ok"}
        if name == "submit_candidate_daily":
            return {"process_run_id": "run-id", "status": "PENDING"}
        if name == "candidate_run_status":
            return {"status": "SUCCEEDED", "terminal": True}
        if name == "fetch_and_verify_candidates":
            return candidates
        if name == "submit_portal_candidate_analysis":
            submissions += 1
            assert payload == {
                "analysis_date": "2026-10-09",
                "selection_run_id": "selection-id",
                "model_purpose": "MEDIUM_20D",
                "candidate_count": 5,
            }
            return {
                **payload,
                "daily_analysis_id": 42,
                "jobs": [{"status": "pending"} for _ in range(5)],
                "terminal": False,
                "succeeded": 0,
                "failed": 0,
            }
        if name == "portal_candidate_analysis_status":
            polls += 1
            return {
                **payload,
                "jobs": [
                    {
                        "status": "completed",
                        "decision": "BUY",
                        "has_result": True,
                        "error": None,
                    }
                    for _ in range(4)
                ]
                + [
                    {
                        "status": "failed",
                        "decision": None,
                        "has_result": False,
                        "error": "analysis_failed",
                    }
                ],
                "terminal": True,
                "succeeded": 4,
                "failed": 1,
            }
        raise AssertionError(name)

    outcome = _run(workflow.daily_orchestrator(FakeContext()), respond)
    assert outcome["state"] == "PARTIAL_FAILED"
    assert outcome["succeeded"] == 4
    assert outcome["failed"] == 1
    assert len(outcome["jobs"]) == 5
    assert outcome["jobs"][-1]["error"] == "analysis_failed"
    assert submissions == 1
    assert polls == 1
