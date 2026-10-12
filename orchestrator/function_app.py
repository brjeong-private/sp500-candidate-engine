"""Python v2 Azure Durable Functions 진입점."""

from __future__ import annotations

import os
from datetime import UTC, datetime

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
from scheduler import orchestration_instance_id, scheduled_analysis_date
from workflow import daily_orchestrator as daily_orchestrator_generator

app = df.DFApp(http_auth_level=func.AuthLevel.FUNCTION)


def _positive_int(name: str, default: int) -> int:
    value = int(os.environ.get(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


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
    instance_id = orchestration_instance_id(analysis_date)
    if await client.get_status(instance_id) is not None:
        return
    await client.start_new(
        "daily_orchestrator",
        instance_id,
        {
            "analysis_date": analysis_date.isoformat(),
            "candidate_timeout_minutes": _positive_int(
                "ORCHESTRATOR_CANDIDATE_TIMEOUT_MINUTES", 120
            ),
            "portal_timeout_minutes": _positive_int("ORCHESTRATOR_PORTAL_TIMEOUT_MINUTES", 360),
            "poll_seconds": _positive_int("ORCHESTRATOR_POLL_SECONDS", 60),
        },
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
@app.activity_trigger(input_name="analysis_date")
def submit_candidate_daily(analysis_date: str):
    return submit_candidate_daily_client(analysis_date)


@app.function_name(name="candidate_run_status")
@app.activity_trigger(input_name="process_run_id")
def candidate_run_status(process_run_id: str):
    return candidate_run_status_client(process_run_id)


@app.function_name(name="fetch_and_verify_candidates")
@app.activity_trigger(input_name="analysis_date")
def fetch_and_verify_candidates(analysis_date: str):
    return fetch_and_verify_candidates_client(analysis_date)


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
