"""외부 API와 Azure control plane을 제한된 HTTP 계약으로 호출한다."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any
from urllib.parse import quote, urlsplit

import httpx
from settings import Settings

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
HTTP_TIMEOUT = httpx.Timeout(30.0, connect=5.0)
CANDIDATE_TERMINAL = {"SUCCEEDED", "PARTIAL_SUCCESS", "FAILED"}
PORTAL_JOB_TERMINAL = {"completed", "failed"}


class ExternalServiceError(RuntimeError):
    """외부 서비스 호출 또는 응답 계약 위반을 나타낸다."""


def _validate_https_url(url: str) -> None:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise ExternalServiceError("outbound URL must use HTTPS without credentials or fragment")


def _read_limited_json(response: httpx.Response) -> dict[str, Any]:
    declared = response.headers.get("content-length")
    if declared:
        try:
            if int(declared) > MAX_RESPONSE_BYTES:
                raise ExternalServiceError("response exceeds size limit")
        except ValueError as error:
            raise ExternalServiceError("invalid Content-Length") from error
    chunks: list[bytes] = []
    size = 0
    for chunk in response.iter_bytes():
        size += len(chunk)
        if size > MAX_RESPONSE_BYTES:
            raise ExternalServiceError("response exceeds size limit")
        chunks.append(chunk)
    try:
        payload = json.loads(b"".join(chunks))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ExternalServiceError("response is not valid JSON") from error
    if not isinstance(payload, dict):
        raise ExternalServiceError("response must be a JSON object")
    return payload


def request_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    expected_statuses: Iterable[int] = (200,),
) -> dict[str, Any]:
    """리디렉션과 대용량 응답을 거부하는 단일 HTTP 요청을 수행한다."""
    _validate_https_url(url)
    try:
        with (
            httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=False) as client,
            client.stream(
                method,
                url,
                headers=headers,
                params=params,
                json=json_body,
            ) as response,
        ):
            if 300 <= response.status_code < 400:
                raise ExternalServiceError("redirect response rejected")
            if response.status_code not in set(expected_statuses):
                raise ExternalServiceError(f"external service returned HTTP {response.status_code}")
            return _read_limited_json(response)
    except httpx.HTTPError as error:
        raise ExternalServiceError("external service request failed") from error


def _candidate_headers(settings: Settings) -> dict[str, str]:
    return {"X-API-Key": settings.candidate_api_key, "Accept": "application/json"}


def _portal_headers(settings: Settings) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.portal_api_key}",
        "Accept": "application/json",
    }


def check_exchange_session(analysis_date: str) -> dict[str, Any]:
    settings = Settings.from_env()
    payload = request_json(
        "GET",
        f"{settings.candidate_base_url}/api/v1/collection-data/exchange-sessions",
        headers=_candidate_headers(settings),
        params={"start_date": analysis_date, "end_date": analysis_date, "limit": 100},
    )
    items = payload.get("items")
    if not isinstance(items, list):
        raise ExternalServiceError("exchange-session response is invalid")
    matching = [
        item
        for item in items
        if isinstance(item, dict)
        and item.get("session_date") == analysis_date
        and item.get("exchange_mic") == settings.exchange_mic
    ]
    return {
        "analysis_date": analysis_date,
        "exchange_mic": settings.exchange_mic,
        "is_session": bool(matching),
    }


def _arm_site(resource_id: str, credential: Any) -> dict[str, Any]:
    token = credential.get_token("https://management.azure.com/.default").token
    return request_json(
        "GET",
        f"https://management.azure.com{resource_id}?api-version=2024-04-01",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )


def readiness_preflight() -> dict[str, str]:
    from azure.identity import DefaultAzureCredential

    settings = Settings.from_env()
    credential = DefaultAzureCredential()
    for name, resource_id in (
        ("candidate", settings.candidate_resource_id),
        ("portal", settings.portal_resource_id),
    ):
        resource = _arm_site(resource_id, credential)
        state = str(resource.get("properties", {}).get("state", "")).upper()
        if state != "RUNNING":
            raise ExternalServiceError(f"{name} App Service is not RUNNING")
    candidate_health = request_json(
        "GET",
        f"{settings.candidate_base_url}/health/ready",
        headers=_candidate_headers(settings),
    )
    portal_health = request_json("GET", f"{settings.portal_base_url}/readyz")
    if candidate_health.get("status") != "ready" or portal_health.get("status") != "ready":
        raise ExternalServiceError("application readiness check failed")
    checked = ["candidate", "portal"]
    if settings.tradingagents_base_url:
        tradingagents_health = request_json("GET", f"{settings.tradingagents_base_url}/readyz")
        if tradingagents_health.get("status") != "ready":
            raise ExternalServiceError("TradingAgents readiness check failed")
        checked.append("tradingagents")
    return {"status": "ready", "checked": ",".join(checked)}


def submit_candidate_daily(request: dict[str, str]) -> dict[str, Any]:
    settings = Settings.from_env()
    analysis_date = request["analysis_date"]
    model_purpose = request["model_purpose"]
    payload = request_json(
        "POST",
        f"{settings.candidate_base_url}/api/v1/pipeline-runs",
        headers={
            **_candidate_headers(settings),
            "Idempotency-Key": f"orchestrator-daily-{analysis_date}-{model_purpose.lower()}",
        },
        json_body={
            "mode": "DAILY",
            "date": analysis_date,
            "with_candidates": True,
        },
        expected_statuses=(202,),
    )
    run_id = payload.get("process_run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ExternalServiceError("Candidate response omitted process_run_id")
    return {"process_run_id": run_id, "status": str(payload.get("status", "PENDING"))}


def candidate_run_status(process_run_id: str) -> dict[str, Any]:
    settings = Settings.from_env()
    payload = request_json(
        "GET",
        f"{settings.candidate_base_url}/api/v1/pipeline-runs/{quote(process_run_id, safe='')}",
        headers=_candidate_headers(settings),
    )
    status = payload.get("status")
    if not isinstance(status, str):
        raise ExternalServiceError("Candidate status response is invalid")
    status = status.upper()
    return {
        "process_run_id": process_run_id,
        "status": status,
        "terminal": status in CANDIDATE_TERMINAL,
        "failure_reason": payload.get("failure_reason"),
    }


def fetch_and_verify_candidates(request: dict[str, str]) -> list[dict[str, Any]]:
    settings = Settings.from_env()
    analysis_date = request["analysis_date"]
    model_purpose = request["model_purpose"]
    cursor: str | None = None
    seen_cursors: set[str] = set()
    items: list[dict[str, Any]] = []
    while True:
        params: dict[str, Any] = {
            "date": analysis_date,
            "model_purpose": model_purpose,
            "limit": 100,
        }
        if cursor:
            params["cursor"] = cursor
        page = request_json(
            "GET",
            f"{settings.candidate_base_url}/api/v1/candidates",
            headers=_candidate_headers(settings),
            params=params,
        )
        page_items = page.get("items")
        if not isinstance(page_items, list):
            raise ExternalServiceError("Candidate list response is invalid")
        items.extend(item for item in page_items if isinstance(item, dict))
        cursor = page.get("next_cursor")
        if cursor is None:
            break
        if not isinstance(cursor, str) or cursor in seen_cursors:
            raise ExternalServiceError("Candidate cursor is invalid")
        seen_cursors.add(cursor)

    if not 5 <= len(items) <= 10:
        raise ExternalServiceError("Candidate selection must contain 5 to 10 items")
    tickers: set[str] = set()
    instruments: set[str] = set()
    selection_runs: set[str] = set()
    verified: list[dict[str, Any]] = []
    for position, item in enumerate(sorted(items, key=lambda value: value.get("position", 0)), 1):
        ticker = item.get("ticker")
        instrument_id = item.get("instrument_id")
        selection_run_id = item.get("selection_run_id")
        if (
            item.get("price_session_date") != analysis_date
            or item.get("status") not in {"SUCCEEDED", "SHORTFALL"}
            or item.get("model_purpose") != model_purpose
            or item.get("selected_count") != len(items)
            or item.get("requested_count") not in range(5, 11)
            or item.get("position") != position
            or not isinstance(ticker, str)
            or not isinstance(instrument_id, str)
            or not isinstance(selection_run_id, str)
            or ticker in tickers
            or instrument_id in instruments
        ):
            raise ExternalServiceError("Candidate selection verification failed")
        tickers.add(ticker)
        instruments.add(instrument_id)
        selection_runs.add(selection_run_id)
        verified.append(
            {
                "ticker": ticker,
                "instrument_id": instrument_id,
                "selection_run_id": selection_run_id,
                "model_purpose": model_purpose,
                "position": position,
            }
        )
    if len(selection_runs) != 1:
        raise ExternalServiceError("Candidate items must belong to one selection run")
    return verified


def _portal_aggregate(
    payload: dict[str, Any],
    *,
    expected_analysis_date: str,
    expected_selection_run_id: str,
    expected_model_purpose: str,
    expected_candidate_count: int,
) -> dict[str, Any]:
    daily_analysis_id = payload.get("daily_analysis_id")
    jobs = payload.get("jobs")
    if (
        not isinstance(daily_analysis_id, int)
        or payload.get("analysis_date") != expected_analysis_date
        or payload.get("selection_run_id") != expected_selection_run_id
        or payload.get("model_purpose") != expected_model_purpose
        or not isinstance(jobs, list)
        or len(jobs) != expected_candidate_count
        or not 5 <= len(jobs) <= 10
    ):
        raise ExternalServiceError("Portal candidate analysis response is invalid")
    normalized_jobs: list[dict[str, Any]] = []
    for job in jobs:
        if not isinstance(job, dict) or job.get("status") not in {
            "pending",
            "running",
            "completed",
            "failed",
        }:
            raise ExternalServiceError("Portal job summary is invalid")
        normalized_jobs.append(
            {
                "status": job["status"],
                "decision": job.get("decision"),
                "has_result": job.get("has_result") is True,
                "error": job.get("error"),
            }
        )
    terminal = all(job["status"] in PORTAL_JOB_TERMINAL for job in normalized_jobs)
    succeeded = sum(job["status"] == "completed" and job["has_result"] for job in normalized_jobs)
    failed = sum(
        job["status"] == "failed" or job["status"] == "completed" and not job["has_result"]
        for job in normalized_jobs
    )
    return {
        "daily_analysis_id": daily_analysis_id,
        "analysis_date": expected_analysis_date,
        "selection_run_id": expected_selection_run_id,
        "model_purpose": expected_model_purpose,
        "candidate_count": expected_candidate_count,
        "jobs": normalized_jobs,
        "terminal": terminal,
        "succeeded": succeeded,
        "failed": failed,
    }


def submit_portal_candidate_analysis(payload: dict[str, Any]) -> dict[str, Any]:
    settings = Settings.from_env()
    analysis_date = str(payload["analysis_date"])
    selection_run_id = str(payload["selection_run_id"])
    model_purpose = str(payload["model_purpose"])
    candidate_count = int(payload["candidate_count"])
    response = request_json(
        "POST",
        f"{settings.portal_base_url}/api/automation/candidate-analyses",
        headers=_portal_headers(settings),
        json_body={
            "analysis_date": analysis_date,
            "selection_run_id": selection_run_id,
            "model_purpose": model_purpose,
        },
        expected_statuses=(202,),
    )
    return _portal_aggregate(
        response,
        expected_analysis_date=analysis_date,
        expected_selection_run_id=selection_run_id,
        expected_model_purpose=model_purpose,
        expected_candidate_count=candidate_count,
    )


def portal_candidate_analysis_status(analysis: dict[str, Any]) -> dict[str, Any]:
    settings = Settings.from_env()
    daily_analysis_id = int(analysis["daily_analysis_id"])
    response = request_json(
        "GET",
        f"{settings.portal_base_url}/api/automation/candidate-analyses/"
        f"{quote(str(daily_analysis_id), safe='')}",
        headers=_portal_headers(settings),
    )
    return _portal_aggregate(
        response,
        expected_analysis_date=str(analysis["analysis_date"]),
        expected_selection_run_id=str(analysis["selection_run_id"]),
        expected_model_purpose=str(analysis["model_purpose"]),
        expected_candidate_count=int(analysis["candidate_count"]),
    )


def send_email(payload: dict[str, Any]) -> dict[str, Any]:
    from azure.communication.email import EmailClient
    from azure.identity import DefaultAzureCredential

    try:
        settings = Settings.from_env()
        client = EmailClient(settings.acs_endpoint, DefaultAzureCredential())
        message = {
            "senderAddress": settings.email_sender,
            "recipients": {
                "to": [{"address": address} for address in settings.email_recipients],
            },
            "content": {
                "subject": str(payload["subject"])[:200],
                "plainText": str(payload["body"])[:20_000],
            },
        }
        result = client.begin_send(message).result(timeout=60)
        return {"sent": True, "id": getattr(result, "id", None)}
    except Exception as error:
        return {"sent": False, "error": type(error).__name__}
