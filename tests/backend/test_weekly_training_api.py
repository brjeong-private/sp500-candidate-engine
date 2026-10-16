from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from backend.app.config import BackendSettings
from backend.app.main import create_app
from backend.app.routers.weekly_training import get_weekly_training_service
from backend.app.schemas.weekly_training import (
    ActivationSmokeResult,
    WeeklyEligibility,
    WeeklyTrainingAccepted,
    WeeklyTrainingStatus,
)
from sp500_candidate_engine.config import Settings
from sp500_candidate_engine.database import Database

RUN_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
MANIFEST_ID = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")


class FakeWeeklyService:
    def eligibility(self):
        return WeeklyEligibility(
            eligible=True,
            iso_week="2026-W42",
            anchor_session=date(2026, 10, 16),
            input_manifest_id=MANIFEST_ID,
            training_cutoff=datetime(2026, 10, 16, 23, tzinfo=UTC),
            label_maturity_cutoff=date(2026, 10, 16),
            reason="READY",
        )

    def accept(self, *, model_purpose, idempotency_key):
        assert idempotency_key == "weekly:2026-W42:SHORT_5D"
        return WeeklyTrainingAccepted(
            weekly_run_id=RUN_ID,
            model_purpose=model_purpose,
            status="PENDING",
            status_url=f"/api/v1/pipeline-runs/weekly/{RUN_ID}",
        )

    def get(self, weekly_run_id):
        return WeeklyTrainingStatus(
            weekly_run_id=weekly_run_id,
            iso_week="2026-W42",
            anchor_session=date(2026, 10, 16),
            model_purpose="SHORT_5D",
            policy_version="weekly-v1",
            input_manifest_id=MANIFEST_ID,
            training_cutoff=datetime(2026, 10, 16, 23, tzinfo=UTC),
            label_maturity_cutoff=date(2026, 10, 16),
            status="PROMOTED",
        )

    def activation_smoke(self, weekly_run_id):
        return ActivationSmokeResult(
            weekly_run_id=weekly_run_id,
            model_purpose="SHORT_5D",
            passed=True,
        )


def _client(monkeypatch):
    from backend.app.services.pipeline_execution import PipelineExecutionService

    monkeypatch.setattr(PipelineExecutionService, "reconcile_interrupted", lambda self: None)
    app = create_app(
        engine_settings=MagicMock(spec=Settings),
        backend_settings=BackendSettings(api_key="x" * 48),
        database=MagicMock(spec=Database),
    )
    app.dependency_overrides[get_weekly_training_service] = FakeWeeklyService
    return TestClient(app)


def test_weekly_endpoints_are_protected_and_safe(monkeypatch):
    with _client(monkeypatch) as client:
        assert client.get("/api/v1/pipeline-runs/weekly/eligibility").status_code == 401
        headers = {"X-API-Key": "x" * 48}
        eligibility = client.get(
            "/api/v1/pipeline-runs/weekly/eligibility", headers=headers
        )
        assert eligibility.status_code == 200
        assert eligibility.json()["iso_week"] == "2026-W42"

        missing_key = client.post(
            "/api/v1/pipeline-runs/weekly",
            headers=headers,
            json={"model_purpose": "SHORT_5D"},
        )
        assert missing_key.status_code == 422

        accepted = client.post(
            "/api/v1/pipeline-runs/weekly",
            headers={**headers, "Idempotency-Key": "weekly:2026-W42:SHORT_5D"},
            json={"model_purpose": "SHORT_5D"},
        )
        assert accepted.status_code == 202
        assert set(accepted.json()) == {
            "weekly_run_id",
            "model_purpose",
            "status",
            "status_url",
        }
        status = client.get(
            f"/api/v1/pipeline-runs/weekly/{RUN_ID}", headers=headers
        )
        assert status.json()["status"] == "PROMOTED"
        smoke = client.post(
            f"/api/v1/pipeline-runs/weekly/{RUN_ID}/activation-smoke",
            headers=headers,
        )
        assert smoke.json()["passed"] is True
