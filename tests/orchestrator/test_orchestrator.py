from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import azure.functions as func
import httpx
import pytest

ORCHESTRATOR_ROOT = Path(__file__).resolve().parents[2] / "orchestrator"
INFRA_ROOT = Path(__file__).resolve().parents[2] / "infra"
sys.path.insert(0, str(ORCHESTRATOR_ROOT))

import clients  # noqa: E402
import function_app  # noqa: E402
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
    assert scheduler.orchestration_instance_id(analysis_date, "MEDIUM_20D") == (
        "candidate-daily-2026-01-11-medium_20d"
    )
    assert scheduler.orchestration_instance_id(analysis_date, "SHORT_5D") == (
        "candidate-daily-2026-01-11-short_5d"
    )


def test_manual_trigger_uses_function_auth():
    manual = next(
        item
        for item in function_app.app.get_functions()
        if item.get_function_name() == "manual_orchestration_start"
    )
    trigger = next(
        binding
        for binding in manual.get_dict_repr()["bindings"]
        if binding["type"] == "httpTrigger"
    )
    assert trigger["authLevel"] == func.AuthLevel.FUNCTION


@pytest.mark.parametrize(
    ("target_date", "model_purpose"),
    [
        ("2026-02-30", "MEDIUM_20D"),
        ("2026-1-01", "MEDIUM_20D"),
        ("2026-10-12", "MEDIUM_20D"),
        ("2026-10-09", "LONG_60D"),
    ],
)
def test_manual_request_fields_are_validated(target_date, model_purpose):
    if model_purpose in scheduler.MODEL_PURPOSES:
        with pytest.raises(ValueError):
            scheduler.validate_target_date(target_date, today=date(2026, 10, 12))
    else:
        with pytest.raises(ValueError):
            scheduler.validate_model_purpose(model_purpose)


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
        candidate_postgres_resource_id=(
            "/subscriptions/sub/resourceGroups/rg/providers/"
            "Microsoft.DBforPostgreSQL/flexibleServers/candidate-db"
        ),
        candidate_postgres_public_network_access="Disabled",
        portal_base_url="https://portal.example.test",
        portal_api_key="portal-key",
        portal_resource_id=(
            "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Web/sites/portal"
        ),
        portal_mysql_resource_id=(
            "/subscriptions/sub/resourceGroups/rg/providers/"
            "Microsoft.DBforMySQL/flexibleServers/portal-db"
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
        orchestrator_storage_public_network_access="Enabled",
        orchestrator_storage_network_default_action="Allow",
        acs_endpoint="https://acs.communication.azure.com",
        email_sender="configured-at-runtime",
        email_recipients=("configured-at-runtime",),
        exchange_mic="XNYS",
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
    result = clients.fetch_and_verify_candidates(
        {"analysis_date": "2026-10-09", "model_purpose": "MEDIUM_20D"}
    )
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
        candidate_postgres_resource_id=(
            "/subscriptions/sub/resourceGroups/rg/providers/"
            "Microsoft.DBforPostgreSQL/flexibleServers/candidate-db"
        ),
        candidate_postgres_public_network_access="Disabled",
        portal_base_url="https://portal.example.test",
        portal_api_key="portal-token",
        portal_resource_id=(
            "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Web/sites/portal"
        ),
        portal_mysql_resource_id=(
            "/subscriptions/sub/resourceGroups/rg/providers/"
            "Microsoft.DBforMySQL/flexibleServers/portal-db"
        ),
        portal_mysql_public_network_access="Disabled",
        tradingagents_base_url=tradingagents_base_url,
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
        orchestrator_storage_public_network_access="Enabled",
        orchestrator_storage_network_default_action="Allow",
        acs_endpoint="https://acs.communication.azure.com",
        email_sender="configured-at-runtime",
        email_recipients=("configured-at-runtime",),
        exchange_mic="XNYS",
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


def test_candidate_submission_idempotency_includes_model_purpose(monkeypatch):
    monkeypatch.setattr(clients.Settings, "from_env", _settings)
    captured = {}

    def fake_request(method, url, **kwargs):
        captured.update(method=method, url=url, **kwargs)
        return {"process_run_id": "run-id", "status": "PENDING"}

    monkeypatch.setattr(clients, "request_json", fake_request)
    clients.submit_candidate_daily({"analysis_date": "2026-10-09", "model_purpose": "SHORT_5D"})

    assert captured["headers"]["Idempotency-Key"] == ("orchestrator-daily-2026-10-09-short_5d")
    assert captured["json_body"] == {
        "mode": "DAILY",
        "date": "2026-10-09",
        "with_candidates": True,
    }


def test_preflight_requires_portal_and_configured_tradingagents_ready(monkeypatch):
    configured = _settings(tradingagents_base_url="https://tradingagents.example.test")
    monkeypatch.setattr(clients.Settings, "from_env", lambda: configured)
    resources = {
        configured.candidate_resource_id: {"properties": {"state": "Running"}},
        configured.portal_resource_id: {"properties": {"state": "Running"}},
        configured.candidate_postgres_resource_id: {
            "properties": {
                "state": "Ready",
                "network": {"publicNetworkAccess": "Disabled"},
            }
        },
        configured.portal_mysql_resource_id: {
            "properties": {
                "state": "Ready",
                "network": {"publicNetworkAccess": "Disabled"},
            }
        },
        configured.tradingagents_resource_id: {
            "properties": {
                "runningStatus": "Running",
                "template": {"scale": {"minReplicas": 1}},
            }
        },
    }
    monkeypatch.setattr(
        clients,
        "_arm_resource",
        lambda resource_id, api_version, credential: resources[resource_id],
    )
    monkeypatch.setattr(
        clients,
        "_check_storage",
        lambda configured, credential, remediated: None,
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

    assert result == {
        "status": "ready",
        "checked": (
            "candidate,candidate_postgresql,portal,portal_mysql,orchestrator_storage,tradingagents"
        ),
        "remediated": "none",
    }
    assert "https://portal.example.test/readyz" in urls
    assert "https://tradingagents.example.test/readyz" in urls


@pytest.mark.parametrize(
    ("name", "api_version", "expected_state"),
    [
        ("candidate_app", clients.APP_SERVICE_API_VERSION, "RUNNING"),
        ("portal_app", clients.APP_SERVICE_API_VERSION, "RUNNING"),
        ("candidate_postgresql", clients.POSTGRES_API_VERSION, "READY"),
        ("portal_mysql", clients.MYSQL_API_VERSION, "READY"),
    ],
)
def test_preflight_starts_stopped_resource_then_rereads(
    monkeypatch,
    name,
    api_version,
    expected_state,
):
    state = {"value": "Stopped"}
    actions = []

    def fake_arm(resource_id, requested_api_version, credential):
        del resource_id, credential
        assert requested_api_version == api_version
        return {"properties": {"state": state["value"]}}

    def fake_action(method, resource_path, requested_api_version, credential, **kwargs):
        del credential, kwargs
        actions.append((method, resource_path, requested_api_version))
        state["value"] = expected_state.title()

    monkeypatch.setattr(clients, "_arm_resource", fake_arm)
    monkeypatch.setattr(clients, "_arm_request", fake_action)
    remediated = []

    clients._ensure_started(
        name,
        "/subscriptions/sub/resourceGroups/rg/providers/Test/resource",
        api_version,
        expected_state,
        object(),
        remediated,
    )

    assert actions == [
        (
            "POST",
            "/subscriptions/sub/resourceGroups/rg/providers/Test/resource/start",
            api_version,
        )
    ]
    assert remediated == [f"{name}:start"]


def test_preflight_fails_only_after_start_does_not_reach_ready(monkeypatch):
    monkeypatch.setattr(
        clients,
        "_arm_resource",
        lambda *args: {"properties": {"state": "Stopped"}},
    )
    monkeypatch.setattr(clients, "_arm_request", lambda *args, **kwargs: None)
    monkeypatch.setattr(clients, "ARM_RECHECK_ATTEMPTS", 2)
    monkeypatch.setattr(clients.time, "sleep", lambda seconds: None)

    with pytest.raises(clients.ExternalServiceError, match="did not reach ready"):
        clients._ensure_started(
            "candidate_app",
            "/subscriptions/sub/resourceGroups/rg/providers/Test/resource",
            clients.APP_SERVICE_API_VERSION,
            "RUNNING",
            object(),
            [],
        )


def test_database_network_mismatch_is_not_auto_remediated():
    with pytest.raises(clients.ExternalServiceError, match="differs from contract"):
        clients._require_database_network(
            "candidate PostgreSQL",
            {"network": {"publicNetworkAccess": "Enabled"}},
            "Disabled",
        )


class FakeCredential:
    def __init__(self):
        self.scopes = []

    def get_token(self, scope):
        self.scopes.append(scope)
        return type("Token", (), {"token": "not-a-real-token"})()


def test_storage_preflight_checks_hardened_contract_and_container_access(monkeypatch):
    configured = _settings()
    credential = FakeCredential()
    storage = {
        "properties": {
            "provisioningState": "Succeeded",
            "allowBlobPublicAccess": False,
            "allowSharedKeyAccess": False,
            "defaultToOAuthAuthentication": True,
            "supportsHttpsTrafficOnly": True,
            "minimumTlsVersion": "TLS1_2",
            "publicNetworkAccess": "Enabled",
            "networkAcls": {"defaultAction": "Allow"},
            "primaryEndpoints": {
                "blob": "https://orchestrator.blob.core.windows.net/",
                "queue": "https://orchestrator.queue.core.windows.net/",
                "table": "https://orchestrator.table.core.windows.net/",
            },
        }
    }
    monkeypatch.setattr(clients, "_arm_resource", lambda *args: storage)
    captured = []
    monkeypatch.setattr(
        clients,
        "request_status",
        lambda method, url, **kwargs: captured.append((method, url, kwargs)),
    )

    clients._check_storage(configured, credential, [])

    assert credential.scopes == [clients.STORAGE_SCOPE]
    assert [(method, url) for method, url, _ in captured] == [
        (
            "HEAD",
            "https://orchestrator.blob.core.windows.net/app-package?restype=container",
        ),
        (
            "GET",
            "https://orchestrator.queue.core.windows.net?comp=list&maxresults=1",
        ),
        (
            "GET",
            "https://orchestrator.table.core.windows.net/Tables?$top=1",
        ),
    ]
    assert all(call["headers"]["Authorization"].startswith("Bearer ") for _, _, call in captured)


def test_storage_preflight_restores_safe_contract(monkeypatch):
    configured = _settings()
    storage = {
        "properties": {
            "provisioningState": "Succeeded",
            "allowBlobPublicAccess": False,
            "allowSharedKeyAccess": True,
            "defaultToOAuthAuthentication": True,
            "supportsHttpsTrafficOnly": True,
            "minimumTlsVersion": "TLS1_2",
            "publicNetworkAccess": "Enabled",
            "networkAcls": {"defaultAction": "Allow"},
            "primaryEndpoints": {
                "blob": "https://orchestrator.blob.core.windows.net/",
                "queue": "https://orchestrator.queue.core.windows.net/",
                "table": "https://orchestrator.table.core.windows.net/",
            },
        }
    }
    monkeypatch.setattr(clients, "_arm_resource", lambda *args: storage)
    mutations = []

    def fake_action(method, resource_path, api_version, credential, **kwargs):
        del credential
        mutations.append((method, resource_path, api_version, kwargs["json_body"]))
        storage["properties"]["allowSharedKeyAccess"] = False

    monkeypatch.setattr(clients, "_arm_request", fake_action)
    monkeypatch.setattr(clients, "request_status", lambda *args, **kwargs: None)
    remediated = []

    clients._check_storage(configured, FakeCredential(), remediated)

    assert mutations[0][0] == "PATCH"
    assert mutations[0][3] == {
        "properties": {
            "allowBlobPublicAccess": False,
            "allowSharedKeyAccess": False,
            "publicNetworkAccess": "Enabled",
            "networkAcls": {"defaultAction": "Allow"},
        }
    }
    assert remediated == ["orchestrator_storage:restore_contract"]


def test_tradingagents_restores_min_replicas_and_running_state(monkeypatch):
    configured = _settings(tradingagents_base_url="https://tradingagents.example.test")
    resource = {
        "properties": {
            "runningStatus": "Stopped",
            "template": {"scale": {"minReplicas": 0}},
        }
    }
    monkeypatch.setattr(clients, "_arm_resource", lambda *args: resource)
    actions = []

    def fake_action(method, resource_path, api_version, credential, **kwargs):
        del resource_path, api_version, credential
        actions.append((method, kwargs.get("json_body")))
        if method == "PATCH":
            resource["properties"]["template"]["scale"]["minReplicas"] = 1
        if method == "POST":
            resource["properties"]["runningStatus"] = "Running"

    monkeypatch.setattr(clients, "_arm_request", fake_action)
    remediated = []

    clients._ensure_tradingagents(configured, object(), remediated)

    assert [method for method, _ in actions] == ["PATCH", "POST"]
    assert remediated == ["tradingagents:min_replicas", "tradingagents:start"]


def test_readonly_lock_is_removed_only_after_scope_locked_and_restored(monkeypatch):
    resource_id = "/subscriptions/sub/resourceGroups/rg/providers/Test/resources/example"
    lock_id = f"{resource_id}/providers/Microsoft.Authorization/locks/guard"
    attempts = 0
    calls = []

    def operation():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise clients.ArmRequestError(409, "ScopeLocked")

    monkeypatch.setattr(
        clients,
        "_resource_readonly_locks",
        lambda candidate_id, credential: [
            {
                "id": lock_id,
                "properties": {
                    "level": "ReadOnly",
                    "notes": "unchanged",
                    "owners": [{"applicationId": "owner-id"}],
                },
            }
        ],
    )
    monkeypatch.setattr(
        clients,
        "_arm_request",
        lambda method, path, version, credential, **kwargs: calls.append(
            (method, path, kwargs.get("json_body"))
        ),
    )

    removed = clients._with_readonly_lock_retry(resource_id, object(), operation)

    assert removed is True
    assert attempts == 2
    assert calls == [
        ("DELETE", lock_id, None),
        (
            "PUT",
            lock_id,
            {
                "properties": {
                    "level": "ReadOnly",
                    "notes": "unchanged",
                    "owners": [{"applicationId": "owner-id"}],
                }
            },
        ),
    ]


def test_readonly_lock_is_restored_when_retry_fails(monkeypatch):
    resource_id = "/subscriptions/sub/resourceGroups/rg/providers/Test/resources/example"
    lock_id = f"{resource_id}/providers/Microsoft.Authorization/locks/guard"
    calls = []
    attempts = 0

    def operation():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise clients.ArmRequestError(409, "ScopeLocked")
        raise clients.ExternalServiceError("still unavailable")

    monkeypatch.setattr(
        clients,
        "_resource_readonly_locks",
        lambda candidate_id, credential: [
            {"id": lock_id, "properties": {"level": "ReadOnly", "notes": "same"}}
        ],
    )
    monkeypatch.setattr(
        clients,
        "_arm_request",
        lambda method, path, version, credential, **kwargs: calls.append(method),
    )

    with pytest.raises(clients.ExternalServiceError, match="still unavailable"):
        clients._with_readonly_lock_retry(
            resource_id,
            object(),
            operation,
        )

    assert calls == ["DELETE", "PUT"]


def test_bicep_requires_and_configures_tradingagents_url():
    template = (INFRA_ROOT / "orchestrator.bicep").read_text(encoding="utf-8")
    assert "param tradingAgentsApiUrl string\n" in template
    assert "param tradingAgentsApiUrl string =" not in template
    assert "name: 'TRADINGAGENTS_API_URL'" in template
    assert "value: tradingAgentsApiUrl" in template


def test_bicep_uses_identity_based_storage_durable_backend():
    template = (INFRA_ROOT / "orchestrator.bicep").read_text(encoding="utf-8")
    assert "Microsoft.DurableTask/" not in template
    assert "DURABLE_TASK_SCHEDULER_CONNECTION_STRING" not in template
    assert "0ad04412-c4d5-4796-b79c-f76d14c8d402" not in template
    assert "name: 'AzureWebJobsStorage__accountName'" in template
    assert "value: storage.name" in template
    assert "name: 'AzureWebJobsStorage__credential'" in template
    assert "value: 'managedidentity'" in template
    assert "b7e6dc6d-f1e8-4753-8033-0f276bb0955b" in template
    assert "974c5e8b-45b9-4653-ba55-5f855dd0fb88" in template
    assert "0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3" in template
    assert template.count("scope: storage") == 3
    assert "allowSharedKeyAccess: false" in template
    assert "allowBlobPublicAccess: false" in template
    assert "supportsHttpsTrafficOnly: true" in template
    assert "minimumTlsVersion: 'TLS1_2'" in template
    assert "publicNetworkAccess: 'Enabled'" in template
    assert "defaultAction: 'Allow'" in template
    assert "type: 'SystemAssigned'" in template
    assert "name: 'FC1'" in template
    assert "type: 'blobContainer'" in template


def test_local_settings_use_storage_emulator_for_durable_backend():
    local_settings = json.loads(
        (ORCHESTRATOR_ROOT / "local.settings.example.json").read_text(encoding="utf-8")
    )
    assert local_settings["Values"]["AzureWebJobsStorage"] == "UseDevelopmentStorage=true"
    assert "DURABLE_TASK_SCHEDULER_CONNECTION_STRING" not in local_settings["Values"]


class FakeContext:
    def __init__(self):
        self.current_utc_datetime = datetime(2026, 10, 12, 10, 30, tzinfo=UTC)

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
            try:
                response = responder(event)
            except Exception as error:
                event = generator.throw(error)
            else:
                event = generator.send(response)
    except StopIteration as stopped:
        return stopped.value


def test_started_email_contains_only_safe_preflight_summary():
    events = []
    preflight = {
        "status": "ready",
        "checked": "candidate,candidate_postgresql,portal,portal_mysql,orchestrator_storage",
        "remediated": "candidate_app:start",
    }
    generator = workflow.daily_orchestrator(FakeContext())

    event = next(generator)
    events.append(event)
    event = generator.send({"is_session": True})
    events.append(event)
    event = generator.send(preflight)
    events.append(event)

    assert [item[1] for item in events] == [
        "check_exchange_session",
        "readiness_preflight",
        "send_email",
    ]
    payload = events[-1][2]
    assert "STARTED" in payload["body"]
    assert "candidate_app:start" in payload["body"]
    assert "/subscriptions/" not in payload["body"]


def test_preflight_failure_occurs_before_started_email_and_pipeline_submission():
    activities = []

    def respond(event):
        assert event[0] == "activity"
        name, payload = event[1], event[2]
        activities.append((name, payload))
        if name == "check_exchange_session":
            return {"is_session": True}
        if name == "readiness_preflight":
            raise clients.ExternalServiceError("candidate PostgreSQL is not READY")
        if name == "send_email":
            return {"sent": True}
        raise AssertionError(name)

    outcome = _run(workflow.daily_orchestrator(FakeContext()), respond)

    assert outcome["state"] == "FAILED"
    assert outcome["reason"] == "ExternalServiceError"
    assert [name for name, _ in activities] == [
        "check_exchange_session",
        "readiness_preflight",
        "send_email",
    ]
    email = activities[-1][1]
    assert "FAILED" in email["subject"]
    assert "STARTED" not in email["subject"]


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
            assert payload == {
                "analysis_date": "2026-10-09",
                "model_purpose": "MEDIUM_20D",
            }
            return {"process_run_id": "run-id", "status": "PENDING"}
        if name == "candidate_run_status":
            return {"status": "SUCCEEDED", "terminal": True}
        if name == "fetch_and_verify_candidates":
            assert payload == {
                "analysis_date": "2026-10-09",
                "model_purpose": "MEDIUM_20D",
            }
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
    assert outcome["model_purpose"] == "MEDIUM_20D"
    assert outcome["succeeded"] == 4
    assert outcome["failed"] == 1
    assert len(outcome["jobs"]) == 5
    assert outcome["jobs"][-1]["error"] == "analysis_failed"
    assert submissions == 1
    assert polls == 1


class FakeRequest:
    def __init__(self, body):
        self._body = body

    def get_json(self):
        return self._body


class FakeDurableClient:
    def __init__(self, existing=None):
        self.existing = existing
        self.started = []

    async def get_status(self, instance_id):
        return self.existing

    async def start_new(self, name, instance_id, client_input):
        self.started.append((name, instance_id, client_input))
        return instance_id

    def create_check_status_response(self, request, instance_id):
        del request
        return func.HttpResponse(
            (
                '{"id":"'
                + instance_id
                + '","statusQueryGetUri":"https://example.test/status?code=secret&taskHub=hub"}'
            ),
            status_code=202,
            headers={
                "Location": "https://example.test/status?code=secret&taskHub=hub",
            },
            mimetype="application/json",
        )


def test_authenticated_manual_start_returns_management_info(monkeypatch):
    monkeypatch.setattr(
        function_app,
        "validate_target_date",
        lambda value: date.fromisoformat(value),
    )
    client = FakeDurableClient()

    response = asyncio.run(
        function_app._manual_orchestration_start(
            FakeRequest(
                {
                    "target_date": "2026-10-09",
                    "model_purpose": "SHORT_5D",
                }
            ),
            client,
        )
    )

    instance_id = "candidate-daily-2026-10-09-short_5d"
    assert response.status_code == 202
    assert b"secret" not in response.get_body()
    assert json.loads(response.get_body()) == {
        "id": instance_id,
        "statusQueryGetUri": "https://example.test/status?taskHub=hub",
    }
    assert response.headers["Location"] == "https://example.test/status?taskHub=hub"
    assert client.started == [
        (
            "daily_orchestrator",
            instance_id,
            {
                "analysis_date": "2026-10-09",
                "model_purpose": "SHORT_5D",
                "candidate_timeout_minutes": 120,
                "portal_timeout_minutes": 360,
                "poll_seconds": 60,
            },
        )
    ]


def test_manual_start_reuses_existing_instance(monkeypatch):
    monkeypatch.setattr(
        function_app,
        "validate_target_date",
        lambda value: date.fromisoformat(value),
    )
    client = FakeDurableClient(existing={"runtime_status": "Running"})

    response = asyncio.run(
        function_app._manual_orchestration_start(
            FakeRequest(
                {
                    "target_date": "2026-10-09",
                    "model_purpose": "MEDIUM_20D",
                }
            ),
            client,
        )
    )

    assert json.loads(response.get_body())["id"] == ("candidate-daily-2026-10-09-medium_20d")
    assert client.started == []


def test_manual_start_rejects_unexpected_fields():
    client = FakeDurableClient()
    response = asyncio.run(
        function_app._manual_orchestration_start(
            FakeRequest(
                {
                    "target_date": "2026-10-09",
                    "model_purpose": "SHORT_5D",
                    "api_key": "must-not-be-accepted",
                }
            ),
            client,
        )
    )

    assert response.status_code == 400
    assert client.started == []
