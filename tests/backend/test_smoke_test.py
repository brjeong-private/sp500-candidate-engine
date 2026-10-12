from __future__ import annotations

import json
import sys
from datetime import timedelta

import httpx
import pytest

from backend import smoke_test

RUN_ID = "d58b5e37-0964-40fe-ba0e-11517566902d"
MODEL_ID = "f75be739-4149-518f-8cbe-1cf6296e619a"


@pytest.mark.parametrize("gateways", [1, 5])
def test_existing_run_poll_is_bounded_and_persists_evidence(tmp_path, monkeypatch, gateways):
    output = tmp_path / "verification.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "smoke_test",
            "--run-mode",
            "DAILY",
            "--existing-run-id",
            RUN_ID,
            "--expected-model-id",
            MODEL_ID,
            "--output",
            str(output),
        ],
    )
    monkeypatch.setattr(smoke_test, "dotenv_values", lambda _: {"BACKEND_API_KEY": "test-key"})
    monkeypatch.setattr(smoke_test.time, "sleep", lambda _: None)
    poll_count = 0
    accepted_posts = []
    candidates = [{"instrument_id": str(i), "model_version_id": MODEL_ID} for i in range(5)]

    def respond(request):
        nonlocal poll_count
        path = request.url.path
        if request.method == "OPTIONS":
            if request.headers["Origin"] != smoke_test.PORTAL_ORIGIN:
                return httpx.Response(400)
            return httpx.Response(
                200,
                headers={
                    "Access-Control-Allow-Origin": smoke_test.PORTAL_ORIGIN,
                    "Access-Control-Allow-Headers": "x-api-key,idempotency-key",
                },
            )
        if request.method == "POST":
            if "X-API-Key" not in request.headers:
                return httpx.Response(401)
            assert "Idempotency-Key" in request.headers
            payload = json.loads(request.content)
            if payload.get("date") == "2099-01-01":
                return httpx.Response(422)
            accepted_posts.append(payload)
            raise AssertionError("Existing run must not be resubmitted")
        if request.url.params.get("start_date") == "2026-09-01":
            return httpx.Response(422)
        if path == f"/api/v1/pipeline-runs/{RUN_ID}":
            poll_count += 1
            if poll_count <= gateways:
                response = httpx.Response(502)
            else:
                response = httpx.Response(200, json={"status": "SUCCEEDED"})
            response.elapsed = timedelta(milliseconds=10)
            return response
        if path == "/api/v1/candidates":
            assert "process_run_id" not in request.url.params
            return httpx.Response(200, json={"items": candidates})
        return httpx.Response(
            200,
            json={"items": []},
            headers={"Access-Control-Allow-Origin": smoke_test.PORTAL_ORIGIN},
        )

    client_class = httpx.Client
    monkeypatch.setattr(
        smoke_test.httpx,
        "Client",
        lambda **kwargs: client_class(transport=httpx.MockTransport(respond), **kwargs),
    )
    if gateways == 5:
        with pytest.raises(httpx.HTTPStatusError):
            smoke_test.main()
    else:
        smoke_test.main()
    report = json.loads(output.read_text(encoding="utf-8"))
    assert len(report["poll_observations"]) == gateways + (gateways == 1)
    assert report["poll_observations"][0]["http_status"] == 502
    assert not accepted_posts
    if gateways == 1:
        assert any(item["name"] == "daily_pinned_model" for item in report["checks"])
    else:
        assert not any(item["name"] == "execution_completed" for item in report["checks"])
