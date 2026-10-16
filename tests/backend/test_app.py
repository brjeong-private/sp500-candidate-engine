from __future__ import annotations

import json
import logging
from unittest.mock import MagicMock

import psycopg
import pytest
from fastapi import Depends
from fastapi.testclient import TestClient

from backend.app.config import PORTAL_ORIGIN, BackendSettings
from backend.app.dependencies import require_api_key
from backend.app.logging import JsonFormatter
from backend.app.main import create_app
from sp500_candidate_engine.config import Settings
from sp500_candidate_engine.database import Database


@pytest.fixture
def app(monkeypatch):
    from backend.app.services.pipeline_execution import PipelineExecutionService

    monkeypatch.setattr(PipelineExecutionService, "reconcile_interrupted", lambda self: None)
    for key, value in {
        "AZURE_SUBSCRIPTION_ID": "test-subscription",
        "AZURE_TENANT_ID": "test-tenant",
        "PGHOST": "localhost",
        "PGDATABASE": "test",
        "PGUSER": "test",
    }.items():
        monkeypatch.setenv(key, value)
    db = MagicMock(spec=Database)
    application = create_app(
        engine_settings=Settings.from_env("not-a-test-env"),
        backend_settings=BackendSettings(api_key="x" * 48),
        database=db,
    )

    @application.post("/test-protected", dependencies=[Depends(require_api_key)])
    def protected():
        return {"ok": True}

    @application.get("/test-error")
    def test_error():
        raise RuntimeError("private payload must not reach callers")

    return application


def test_health_and_origin_cors(app):
    with TestClient(app) as client:
        result = client.get("/health/live", headers={"Origin": PORTAL_ORIGIN})
        assert result.status_code == 200
        assert result.json() == {"status": "ok"}
        assert result.headers["access-control-allow-origin"] == PORTAL_ORIGIN
        assert "x-request-id" in result.headers
        assert (
            "access-control-allow-origin"
            not in client.get(
                "/health/live", headers={"Origin": "https://untrusted.example"}
            ).headers
        )
        assert client.get("/health/ready").status_code == 200


def test_preflight_and_api_key(app):
    with TestClient(app) as client:
        response = client.options(
            "/api/v1/pipeline-runs",
            headers={
                "Origin": PORTAL_ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "x-api-key,content-type,idempotency-key",
            },
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == PORTAL_ORIGIN
        assert "x-api-key" in response.headers["access-control-allow-headers"].lower()
        assert "idempotency-key" in response.headers["access-control-allow-headers"].lower()
        denied = client.options(
            "/api/v1/pipeline-runs",
            headers={
                "Origin": "https://untrusted.example",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert denied.status_code == 400
        assert "access-control-allow-origin" not in denied.headers
        assert client.post("/test-protected").status_code == 401
        assert client.post("/test-protected", headers={"X-API-Key": "wrong"}).status_code == 401
        assert client.post("/test-protected", headers={"X-API-Key": "x" * 48}).status_code == 200


def test_readiness_failure_and_errors_keep_cors(app):
    with TestClient(app, raise_server_exceptions=False) as client:
        app.state.database.connect.side_effect = psycopg.OperationalError(
            "test database unavailable"
        )
        response = client.get("/health/ready", headers={"Origin": PORTAL_ORIGIN})
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "DATABASE_UNAVAILABLE"
        assert response.headers["access-control-allow-origin"] == PORTAL_ORIGIN
        assert "test database unavailable" not in response.text
        schema = client.get("/openapi.json").json()
        assert "/api/v1/candidates" in schema["paths"]
        assert "/api/v1/llm-preselections" in schema["paths"]
        assert "/api/v1/collection-data/{dataset}" in schema["paths"]
        assert "ErrorResponse" in schema["components"]["schemas"]


def test_unexpected_error_keeps_cors_and_redacts_payload(app):
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/test-error", headers={"Origin": PORTAL_ORIGIN})
        assert response.status_code == 500
        assert response.headers["access-control-allow-origin"] == PORTAL_ORIGIN
        assert response.json()["error"]["code"] == "INTERNAL_ERROR"
        assert "private payload" not in response.text


@pytest.mark.parametrize(
    "origin",
    ["*", "https://example.com/path", "https://example.com/", "http://example.com"],
)
def test_invalid_config_rejected(monkeypatch, origin):
    monkeypatch.setenv("BACKEND_API_KEY", "x" * 48)
    monkeypatch.setenv("BACKEND_CORS_ORIGINS", origin)
    with pytest.raises(ValueError):
        BackendSettings.from_env()


def test_api_key_not_in_settings_repr():
    assert "x" * 48 not in repr(BackendSettings(api_key="x" * 48))


def test_log_formatter_keeps_structured_context_without_exception_payload():
    record = logging.LogRecord(
        "candidate_api", logging.ERROR, __file__, 1, "database_error", (), None
    )
    record.request_id = "request-test"
    record.status = 503
    record.exc_info = (ValueError, ValueError("sensitive provider payload"), None)
    result = json.loads(JsonFormatter().format(record))
    assert result["request_id"] == "request-test"
    assert result["status"] == 503
    assert result["exception_type"] == "ValueError"
    assert "sensitive provider payload" not in json.dumps(result)
