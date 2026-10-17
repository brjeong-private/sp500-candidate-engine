from __future__ import annotations

import copy
import sys
from datetime import UTC, date, datetime
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.repositories.fusions import FusionReadRepository
from backend.app.routers import fusions
from backend.app.schemas.fusions import FusionRun
from sp500_candidate_engine.database import _canonical_hash

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "orchestrator"))
import clients  # noqa: E402
import fusion_contract  # noqa: E402
import workflow  # noqa: E402

RUN = UUID(int=1001)
QUANT = UUID(int=1002)
LLM = UUID(int=1003)
CONTEXT = UUID(int=1004)
DAY = date(2026, 10, 14)
NOW = datetime(2026, 10, 15, 9, 30, tzinfo=UTC)


def row():
    candidates = []
    for position in range(1, 21):
        score = Fraction(2, 10 + position)
        candidates.append({
            "instrument_id": UUID(int=position), "issuer_id": UUID(int=position + 100),
            "ticker": f"T{position}", "sector": f"S{position % 10}", "position": position,
            "quant_rank": position, "quant_rank_overall": position + 100,
            "quant_predicted_return": -0.01 if position == 20 else 0.1,
            "llm_rank": position, "llm_assessment_rank": position + 10, "llm_score": 75.3571,
            "rrf_score": float(score), "rrf_numerator": score.numerator,
            "rrf_denominator": score.denominator,
            "selected_by_quant": True, "selected_by_llm": True,
            "quality_status": "OK", "risk_status": "PASSED", "reason_codes": ["RRF_BOTH"],
            "source_evidence_refs": [UUID(int=position + 10000)],
        })
    return {
        "fusion_run_id": RUN, "execution_context_id": CONTEXT,
        "quant_selection_run_id": QUANT, "llm_preselection_run_id": LLM,
        "price_session_date": DAY, "cutoff_at": NOW, "generated_at": NOW,
        "model_purpose": "MEDIUM_20D", "selection_type": "FUSION",
        "policy_version": "daily-medium-20d-rrf:1", "config_hash": "a" * 64, "rrf_k": 10,
        "requested_count": 20, "selected_count": 20, "union_count": 20,
        "status": "SUCCEEDED", "failure_code": None, "sector_cap_relaxed": False,
        "provenance": {"manifest_hash": "b" * 64}, "payload_hash": "c" * 64,
        "created_at": NOW, "candidates": candidates,
    }


def envelope(monkeypatch):
    monkeypatch.setattr(FusionReadRepository, "fetch", lambda *args: [row()])
    return FusionReadRepository(MagicMock()).handoff(RUN)


def settings(**changes):
    return SimpleNamespace(
        **{
            "fusion_enabled": True, "fusion_external_delivery_enabled": True,
            "fusion_external_contract_version": "fusion-top20-v1",
            "fusion_policy_version": "daily-medium-20d-rrf:1",
            "fusion_config_hash": "a" * 64,
            "fusion_handoff_path": "/api/automation/candidate-handoffs",
            "candidate_base_url": "https://candidate.example.test",
            "candidate_api_key": "test-only", "portal_base_url": "https://portal.example.test",
            "portal_api_key": "test-only",
            **changes,
        }
    )


def ack(payload):
    return {
        "contract_version": "fusion-top20-v1", "selection_run_id": str(RUN),
        "payload_hash": payload["payload_hash"], "status": "ACCEPTED", "accepted_count": 20,
        "accepted_candidates": [
            {key: item[key] for key in ("instrument_id", "issuer_id", "position")}
            for item in payload["candidates"]
        ],
    }


def test_api_handoff_and_independent_consumer_agree_on_exact_wire_contract(monkeypatch):
    payload = envelope(monkeypatch)
    identities = fusion_contract.verify_envelope(
        payload, run_id=str(RUN), analysis_date=DAY.isoformat(),
        policy_version="daily-medium-20d-rrf:1", quant_id=str(QUANT), llm_id=str(LLM),
        expected_config_hash="a" * 64,
    )
    assert len(identities) == 20
    assert payload["rrf_k"] == 10
    assert payload["candidates"][19]["quant_predicted_return"] == -0.01
    assert payload["payload_hash"] == _canonical_hash({
        key: value for key, value in payload.items() if key != "payload_hash"
    })
    fusion_contract.verify_ack(ack(payload), payload, identities)


def test_api_routes_serve_stored_run_and_reject_short_fusion(monkeypatch):
    application = FastAPI()
    application.state.database = MagicMock()
    application.include_router(fusions.router)
    calls = []

    def fetch(_self, sql, parameters):
        calls.append((sql, parameters))
        result = row()
        if "_anchor" in sql:
            result["_anchor"] = NOW
        return [result]

    monkeypatch.setattr(FusionReadRepository, "fetch", fetch)
    with TestClient(application) as client:
        response = client.get(f"/api/v1/fusion-selections/{RUN}")
        assert response.status_code == 200
        assert len(response.json()["candidates"]) == 20
        response = client.get(f"/api/v1/fusion-selections/{RUN}/handoff")
        assert response.status_code == 200
        assert response.json()["selection_type"] == "FUSION"
        response = client.get("/api/v1/fusion-selections", params={"date": str(DAY)})
        assert response.status_code == 200
        assert calls[-1][1] == [None, DAY, DAY, 101]
        assert client.get(
            "/api/v1/fusion-selections", params={"model_purpose": "SHORT_5D"}
        ).status_code == 422


@pytest.mark.parametrize("status", ["SHORTFALL", "FAILED"])
def test_incomplete_fusion_can_be_inspected_but_cannot_be_handed_off(monkeypatch, status):
    incomplete = row()
    incomplete.update(status=status, selected_count=0, candidates=[], failure_code="TEST_FAILURE")
    monkeypatch.setattr(FusionReadRepository, "fetch", lambda *args: [copy.deepcopy(incomplete)])
    repository = FusionReadRepository(MagicMock())
    assert repository.get_run(RUN).status == status
    with pytest.raises(Exception) as error:
        repository.handoff(RUN)
    assert error.value.status_code == 409


@pytest.mark.parametrize("change", [
    lambda value: value.update(selected_count=19),
    lambda value: value["candidates"][0].update(issuer_id=str(UUID(int=102))),
    lambda value: value["candidates"][0].update(rrf_numerator=999),
    lambda value: value["candidates"][0].update(llm_rank=None),
    lambda value: value.update(raw_payload="not allowed"),
])
def test_wire_rejects_bad_count_identity_score_or_unapproved_fields(monkeypatch, change):
    payload = envelope(monkeypatch)
    change(payload)
    payload["payload_hash"] = fusion_contract.canonical_hash({
        key: value for key, value in payload.items() if key != "payload_hash"
    })
    with pytest.raises((ValueError, TypeError)):
        fusion_contract.verify_envelope(
            payload, run_id=str(RUN), analysis_date=str(DAY),
            policy_version="daily-medium-20d-rrf:1", quant_id=str(QUANT), llm_id=str(LLM),
            expected_config_hash="a" * 64,
        )


def test_external_submission_is_whole20_and_idempotent_across_transport_retry(monkeypatch):
    payload = envelope(monkeypatch)
    monkeypatch.setattr(clients.Settings, "from_env", settings)
    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if len(calls) == 1:
            raise clients.ExternalServiceError("timeout", retryable=True)
        return ack(payload)

    monkeypatch.setattr(clients, "request_json", request)
    assert clients.submit_fusion_handoff(payload)["delivery_status"] == "RETRYABLE_FAILURE"
    assert clients.submit_fusion_handoff(payload)["delivery_status"] == "ACKNOWLEDGED"
    assert calls[0][2]["headers"]["Idempotency-Key"] == calls[1][2]["headers"]["Idempotency-Key"]
    assert len(calls[1][2]["json_body"]["candidates"]) == 20


@pytest.mark.parametrize("modification", [
    lambda value: value.update(accepted_count=19),
    lambda value: value.update(payload_hash="wrong"),
    lambda value: value["accepted_candidates"][0].update(instrument_id=str(UUID(int=999))),
])
def test_partial_or_wrong_ack_is_failure_not_retryable_success(monkeypatch, modification):
    payload = envelope(monkeypatch)
    monkeypatch.setattr(clients.Settings, "from_env", settings)
    response = ack(payload)
    modification(response)
    monkeypatch.setattr(clients, "request_json", lambda *args, **kwargs: response)
    with pytest.raises(clients.ExternalServiceError, match="acknowledge"):
        clients.submit_fusion_handoff(payload)


def test_delivery_flag_blocks_all_external_io(monkeypatch):
    payload = envelope(monkeypatch)
    monkeypatch.setattr(
        clients.Settings, "from_env", lambda: settings(fusion_external_delivery_enabled=False)
    )
    request = MagicMock()
    monkeypatch.setattr(clients, "request_json", request)
    with pytest.raises(clients.ExternalServiceError, match="disabled"):
        clients.submit_fusion_handoff(payload)
    request.assert_not_called()


def test_existing_quant_does_not_skip_unfinished_fusion_stage(monkeypatch):
    monkeypatch.setattr(clients.Settings, "from_env", settings)
    monkeypatch.setattr(clients, "fetch_and_verify_candidates", lambda _: [{
        "selection_run_id": str(QUANT)
    }] * 20)
    monkeypatch.setattr(clients, "candidate_run_status", lambda _: {
        "terminal": False, "status": "PENDING"
    })
    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if method == "GET":
            return {"items": []}
        return {"process_run_id": str(UUID(int=3000)), "status": "PENDING"}

    monkeypatch.setattr(clients, "request_json", request)
    response = clients.submit_candidate_daily({
        "analysis_date": str(DAY), "model_purpose": "MEDIUM_20D", "fusion_enabled": True,
    })
    assert response["status"] == "PENDING"
    assert [method for method, _, _ in calls] == ["GET", "POST"]
    assert calls[0][2]["params"]["config_hash"] == "a" * 64


def test_terminal_failed_request_resumes_under_a_new_stage_retry_key(monkeypatch):
    monkeypatch.setattr(clients.Settings, "from_env", settings)
    monkeypatch.setattr(clients, "fetch_and_verify_candidates", lambda _: [])
    calls = []
    identifiers = [str(UUID(int=3100)), str(UUID(int=3101))]

    def request(method, url, **kwargs):
        calls.append(kwargs)
        return {"process_run_id": identifiers[len(calls) - 1]}

    monkeypatch.setattr(clients, "request_json", request)
    monkeypatch.setattr(clients, "candidate_run_status", lambda identifier: (
        {"terminal": True, "status": "FAILED", "fusion_status": "FAILED"}
        if identifier == identifiers[0] else {"terminal": False, "status": "PENDING"}
    ))
    response = clients.submit_candidate_daily({
        "analysis_date": str(DAY), "model_purpose": "MEDIUM_20D", "fusion_enabled": True,
    })
    assert response["process_run_id"] == identifiers[1]
    assert calls[0]["headers"]["Idempotency-Key"] != calls[1]["headers"]["Idempotency-Key"]
    assert "-retry-" in calls[1]["headers"]["Idempotency-Key"]
    assert calls[0]["json_body"] == calls[1]["json_body"]


def test_ready_fusion_resumes_without_new_candidate_or_analysis_run(monkeypatch):
    payload = envelope(monkeypatch)
    request = {
        "analysis_date": str(DAY), "model_purpose": "MEDIUM_20D",
        "fusion_enabled": True, "fusion_external_delivery_enabled": True,
        "candidate_timeout_minutes": 120, "portal_timeout_minutes": 360, "poll_seconds": 60,
    }

    class Context:
        instance_id = "test-instance"
        current_utc_datetime = NOW

        def get_input(self):
            return request

        def call_activity(self, name, value):
            return name, value

        def create_timer(self, deadline):
            return "timer", deadline

    responses = {
        "check_exchange_session": {"is_session": True, "data_complete": True},
        "readiness_preflight": {"status": "ready"},
        "submit_candidate_daily": {
            "status": "FUSION_READY", "fusion_run_id": str(RUN),
            "candidate_selection_run_id": str(QUANT), "llm_preselection_run_id": str(LLM),
        },
        "fetch_fusion_handoff": payload,
        "submit_fusion_handoff": {"delivery_status": "ACKNOWLEDGED"},
        "send_email": {"sent": False, "disabled": True},
        "emit_pipeline_telemetry": {},
    }
    generator = workflow.daily_orchestrator(Context())
    response = None
    names = []
    while True:
        try:
            name, value = generator.send(response)
        except StopIteration as finished:
            result = finished.value
            break
        names.append(name)
        response = responses[name]
    assert result["state"] == "SUCCEEDED"
    assert result["submitted_candidates"] == 20
    assert "candidate_run_status" not in names
    assert "fetch_and_verify_candidates" not in names
    assert "submit_portal_candidate_analysis" not in names
    assert names.count("submit_fusion_handoff") == 1


def test_persistence_shape_validator_rejects_fake_success():
    invalid = row()
    invalid["candidates"] = invalid["candidates"][:19]
    with pytest.raises(ValueError, match="shape"):
        FusionRun.model_validate(invalid)
