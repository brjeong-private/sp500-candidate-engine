"""Python v2 Azure Durable Functions 진입점."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import azure.durable_functions as df
import azure.functions as func
from clients import (
    candidate_run_status as candidate_run_status_client,
)
from clients import (
    check_exchange_session as check_exchange_session_client,
)
from clients import (
    fetch_and_verify_candidates as fetch_and_verify_candidates_client,
)
from clients import (
    portal_candidate_analysis_status as portal_candidate_analysis_status_client,
)
from clients import (
    readiness_preflight as readiness_preflight_client,
)
from clients import (
    send_email as send_email_client,
)
from clients import (
    submit_candidate_daily as submit_candidate_daily_client,
)
from clients import (
    submit_portal_candidate_analysis as submit_portal_candidate_analysis_client,
)
from scheduler import (
    TIMER_MODEL_PURPOSE,
    orchestration_instance_id,
    scheduled_analysis_date,
    validate_model_purpose,
    validate_target_date,
)
from workflow import daily_orchestrator as daily_orchestrator_generator

app = df.DFApp(http_auth_level=func.AuthLevel.FUNCTION)


def _positive_int(name: str, default: int) -> int:
    value = int(os.environ.get(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def _orchestration_input(analysis_date, model_purpose: str) -> dict[str, object]:
    return {
        "analysis_date": analysis_date.isoformat(),
        "model_purpose": model_purpose,
        "candidate_timeout_minutes": _positive_int("ORCHESTRATOR_CANDIDATE_TIMEOUT_MINUTES", 120),
        "portal_timeout_minutes": _positive_int("ORCHESTRATOR_PORTAL_TIMEOUT_MINUTES", 360),
        "poll_seconds": _positive_int("ORCHESTRATOR_POLL_SECONDS", 60),
    }


def _error_response(message: str) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps({"error": message}),
        status_code=400,
        mimetype="application/json",
    )


def _without_code_query(value: str) -> str:
    parsed = urlsplit(value)
    if not parsed.scheme or not parsed.netloc:
        return value
    query = urlencode(
        [(key, item) for key, item in parse_qsl(parsed.query) if key.casefold() != "code"]
    )
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, parsed.fragment))


def _safe_management_response(response: func.HttpResponse) -> func.HttpResponse:
    payload = json.loads(response.get_body())
    if not isinstance(payload, dict):
        raise ValueError("Durable management response must be a JSON object")
    safe_payload = {
        key: _without_code_query(value) if isinstance(value, str) else value
        for key, value in payload.items()
    }
    headers = {
        key: _without_code_query(value)
        for key, value in response.headers.items()
        if key.casefold() not in {"content-length", "content-type"}
    }
    return func.HttpResponse(
        json.dumps(safe_payload),
        status_code=response.status_code,
        headers=headers,
        mimetype="application/json",
    )


@app.function_name(name="manual_orchestration_start")
@app.route(
    route="orchestrations/manual",
    methods=["POST"],
    auth_level=func.AuthLevel.FUNCTION,
)
@app.durable_client_input(client_name="client")
async def manual_orchestration_start(
    req: func.HttpRequest,
    client: df.DurableOrchestrationClient,
) -> func.HttpResponse:
    return await _manual_orchestration_start(req, client)


async def _manual_orchestration_start(
    req: func.HttpRequest,
    client: df.DurableOrchestrationClient,
) -> func.HttpResponse:
    try:
        body = req.get_json()
        if not isinstance(body, dict):
            raise ValueError("request body must be a JSON object")
        if set(body) != {"target_date", "model_purpose"}:
            raise ValueError("request must contain only target_date and model_purpose")
        analysis_date = validate_target_date(body["target_date"])
        model_purpose = validate_model_purpose(body["model_purpose"])
    except ValueError as error:
        return _error_response(str(error))

    instance_id = orchestration_instance_id(analysis_date, model_purpose)
    if await client.get_status(instance_id) is None:
        await client.start_new(
            "daily_orchestrator",
            instance_id,
            _orchestration_input(analysis_date, model_purpose),
        )
    return _safe_management_response(client.create_check_status_response(req, instance_id))


@app.function_name(name="hourly_timer")
@app.timer_trigger(
    schedule="0 30 * * * *",
    arg_name="timer",
    run_on_startup=False,
    use_monitor=True,
)
@app.durable_client_input(client_name="client")
async def hourly_timer(timer: func.TimerRequest, client: df.DurableOrchestrationClient) -> None:
    del timer
    analysis_date = scheduled_analysis_date(datetime.now(UTC))
    if analysis_date is None:
        return
    instance_id = orchestration_instance_id(analysis_date, TIMER_MODEL_PURPOSE)
    if await client.get_status(instance_id) is not None:
        return
    await client.start_new(
        "daily_orchestrator",
        instance_id,
        _orchestration_input(analysis_date, TIMER_MODEL_PURPOSE),
    )


@app.function_name(name="daily_orchestrator")
@app.orchestration_trigger(context_name="context")
def daily_orchestrator(context: df.DurableOrchestrationContext):
    return daily_orchestrator_generator(context)


@app.function_name(name="check_exchange_session")
@app.activity_trigger(input_name="analysis_date")
def check_exchange_session(analysis_date: str):
    return check_exchange_session_client(analysis_date)


@app.function_name(name="readiness_preflight")
@app.activity_trigger(input_name="_unused")
def readiness_preflight(_unused):
    del _unused
    return readiness_preflight_client()


@app.function_name(name="submit_candidate_daily")
@app.activity_trigger(input_name="request")
def submit_candidate_daily(request: dict[str, str]):
    return submit_candidate_daily_client(request)


@app.function_name(name="candidate_run_status")
@app.activity_trigger(input_name="process_run_id")
def candidate_run_status(process_run_id: str):
    return candidate_run_status_client(process_run_id)


@app.function_name(name="fetch_and_verify_candidates")
@app.activity_trigger(input_name="request")
def fetch_and_verify_candidates(request: dict[str, str]):
    return fetch_and_verify_candidates_client(request)


@app.function_name(name="submit_portal_candidate_analysis")
@app.activity_trigger(input_name="payload")
def submit_portal_candidate_analysis(payload: dict):
    return submit_portal_candidate_analysis_client(payload)


@app.function_name(name="portal_candidate_analysis_status")
@app.activity_trigger(input_name="analysis")
def portal_candidate_analysis_status(analysis: dict):
    return portal_candidate_analysis_status_client(analysis)


@app.function_name(name="send_email")
@app.activity_trigger(input_name="payload")
def send_email(payload: dict):
    return send_email_client(payload)
