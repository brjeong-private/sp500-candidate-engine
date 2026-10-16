"""외부 I/O 없이 Durable 작업과 타이머만 예약하는 결정적 흐름."""

from __future__ import annotations

from collections.abc import Generator
from datetime import timedelta
from typing import Any

MODEL_SEQUENCE = ("SHORT_5D", "MEDIUM_20D")
CORE_STAGES = frozenset(
    {
        "eligibility",
        "preflight",
        "candidate",
        "candidate_submit",
        "candidate_poll",
        "candidate_fetch",
        "core",
        "orchestrator",
    }
)
SAFE_EMAIL_FIELDS = frozenset(
    {
        "analysis_date",
        "candidate_count",
        "daily_analysis_id",
        "failed",
        "model_purpose",
        "process_run_id",
        "reason",
        "selection_run_id",
        "stage",
        "state",
        "submitted_candidates",
        "succeeded",
    }
)


class _EmailDeliveryFailed(RuntimeError):
    pass


def result(
    state: str,
    analysis_date: str,
    model_purpose: str,
    **details: Any,
) -> dict[str, Any]:
    return {
        "state": state,
        "analysis_date": analysis_date,
        "model_purpose": model_purpose,
        **details,
    }


def _email(subject: str, body: dict[str, Any]) -> dict[str, str]:
    return {"subject": subject, "body": str(body)}


def _model_subject(model_purpose: str, analysis_date: str, state: str) -> str:
    return f"[candidate-orchestrator] {model_purpose} {analysis_date} {state}"


def _terminal_email(
    model_purpose: str,
    analysis_date: str,
    final: dict[str, Any],
) -> dict[str, str]:
    safe_body = {key: value for key, value in final.items() if key in SAFE_EMAIL_FIELDS}
    return _email(
        _model_subject(model_purpose, analysis_date, str(final["state"])),
        safe_body,
    )


def _require_email_delivery(response: Any) -> None:
    if _email_delivery_failed(response):
        raise _EmailDeliveryFailed


def _email_delivery_failed(response: Any) -> bool:
    return (
        isinstance(response, dict)
        and response.get("sent") is False
        and response.get("disabled") is not True
    )


def _model_summary(instance_id: str, child_result: dict[str, Any]) -> dict[str, Any]:
    return {
        "instance_id": instance_id,
        "state": str(child_result.get("state", "FAILED")),
        "result": child_result,
    }


def _short_core_failure(child_result: dict[str, Any]) -> bool:
    return (
        child_result.get("state") in {"FAILED", "TIMED_OUT"}
        and child_result.get("stage") in CORE_STAGES
    )


def _aggregate_state(models: dict[str, dict[str, Any]]) -> str:
    states = {model["state"] for model in models.values()}
    for state in ("FAILED", "TIMED_OUT", "PARTIAL_FAILED"):
        if state in states:
            return state
    return "SUCCEEDED"


def _telemetry_payload(
    event: str,
    state: str,
    *,
    context: Any,
    request: dict[str, Any],
    stage: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    details = details or {}
    return {
        "event": event,
        "parent_instance_id": request.get("parent_instance_id"),
        "model_instance_id": (
            getattr(context, "instance_id", None) if request.get("model_purpose") else None
        ),
        "target_session": request.get("analysis_date"),
        "model_purpose": request.get("model_purpose"),
        "candidate_process_run_id": details.get(
            "candidate_process_run_id", details.get("process_run_id")
        ),
        "selection_run_id": details.get("selection_run_id"),
        "daily_analysis_id": details.get("daily_analysis_id"),
        "state": state,
        "stage": stage,
        "remediated": details.get("remediated", False),
    }


def _emit(
    context: Any,
    event: str,
    state: str,
    *,
    request: dict[str, Any],
    stage: str,
    details: dict[str, Any] | None = None,
) -> Generator[Any, Any, None]:
    try:
        yield context.call_activity(
            "emit_pipeline_telemetry",
            _telemetry_payload(
                event,
                state,
                context=context,
                request=request,
                stage=stage,
                details=details,
            ),
        )
    except Exception:
        return


def _finish_model(
    context: Any,
    request: dict[str, Any],
    final: dict[str, Any],
) -> Generator[Any, Any, dict[str, Any]]:
    yield from _emit(
        context,
        "pipeline.model.terminal",
        str(final["state"]),
        request=request,
        stage=str(final.get("stage", "terminal")),
        details=final,
    )
    return final


def _send_email(
    context: Any,
    request: dict[str, Any],
    payload: dict[str, str],
    *,
    stage: str,
) -> Generator[Any, Any, Any]:
    try:
        response = yield context.call_activity("send_email", payload)
    except Exception:
        yield from _emit(
            context,
            "pipeline.email.terminal",
            "FAILED",
            request=request,
            stage=stage,
        )
        raise
    disabled = isinstance(response, dict) and response.get("disabled") is True
    sent = not _email_delivery_failed(response) and not disabled
    yield from _emit(
        context,
        "pipeline.email.terminal",
        "SKIPPED" if disabled else "SUCCEEDED" if sent else "FAILED",
        request=request,
        stage=stage,
    )
    return response


def dual_model_parent(context: Any) -> Generator[Any, Any, dict[str, Any]]:
    request = context.get_input()
    analysis_date = str(request["analysis_date"])
    child_instance_ids = request["child_instance_ids"]
    parent_instance_id = getattr(context, "instance_id", None)
    parent_request = {**request, "parent_instance_id": parent_instance_id}
    yield from _emit(
        context,
        "pipeline.parent.started",
        "STARTED",
        request=parent_request,
        stage="parent",
    )
    common_input = {
        "analysis_date": analysis_date,
        "candidate_timeout_minutes": request["candidate_timeout_minutes"],
        "portal_timeout_minutes": request["portal_timeout_minutes"],
        "poll_seconds": request["poll_seconds"],
        "parent_instance_id": parent_instance_id,
    }
    models: dict[str, dict[str, Any]] = {}

    short_input = {**common_input, "model_purpose": MODEL_SEQUENCE[0]}
    short_result = yield context.call_sub_orchestrator(
        "daily_orchestrator",
        short_input,
        child_instance_ids[MODEL_SEQUENCE[0]],
    )
    models[MODEL_SEQUENCE[0]] = _model_summary(
        child_instance_ids[MODEL_SEQUENCE[0]],
        short_result,
    )

    if _short_core_failure(short_result):
        models[MODEL_SEQUENCE[1]] = {
            "instance_id": child_instance_ids[MODEL_SEQUENCE[1]],
            "state": "NOT_STARTED",
            "reason": "short_core_failure",
        }
        final = {
            "state": short_result["state"],
            "analysis_date": analysis_date,
            "models": models,
            "stopped_after": MODEL_SEQUENCE[0],
        }
        yield from _emit(
            context,
            "pipeline.parent.terminal",
            str(final["state"]),
            request=parent_request,
            stage="parent",
        )
        return final

    medium_input = {**common_input, "model_purpose": MODEL_SEQUENCE[1]}
    medium_result = yield context.call_sub_orchestrator(
        "daily_orchestrator",
        medium_input,
        child_instance_ids[MODEL_SEQUENCE[1]],
    )
    models[MODEL_SEQUENCE[1]] = _model_summary(
        child_instance_ids[MODEL_SEQUENCE[1]],
        medium_result,
    )
    final = {
        "state": _aggregate_state(models),
        "analysis_date": analysis_date,
        "models": models,
    }
    yield from _emit(
        context,
        "pipeline.parent.terminal",
        str(final["state"]),
        request=parent_request,
        stage="parent",
    )
    return final


def daily_orchestrator(context: Any) -> Generator[Any, Any, dict[str, Any]]:
    request = context.get_input()
    analysis_date = str(request["analysis_date"])
    model_purpose = str(request["model_purpose"])
    candidate_timeout = timedelta(minutes=int(request["candidate_timeout_minutes"]))
    portal_timeout = timedelta(minutes=int(request["portal_timeout_minutes"]))
    poll_interval = timedelta(seconds=int(request["poll_seconds"]))
    failure_code = "ELIGIBILITY_CHECK_FAILED"
    failure_stage = "eligibility"
    terminal_email_attempted = False

    try:
        yield from _emit(
            context,
            "pipeline.model.started",
            "STARTED",
            request=request,
            stage="model",
        )
        session = yield context.call_activity("check_exchange_session", analysis_date)
        if not session["is_session"]:
            final = result(
                "SUCCEEDED",
                analysis_date,
                model_purpose,
                skipped=True,
                reason="not_exchange_session",
            )
            return (yield from _finish_model(context, request, final))
        if not session["data_complete"]:
            failure_code = "ELIGIBILITY_DATA_INCOMPLETE"
            raise RuntimeError

        failure_code = "PREFLIGHT_FAILED"
        failure_stage = "preflight"
        preflight = yield context.call_activity("readiness_preflight", None)
        candidate_request = {
            "analysis_date": analysis_date,
            "model_purpose": model_purpose,
        }
        failure_code = "CANDIDATE_SUBMIT_FAILED"
        failure_stage = "candidate_submit"
        accepted = yield context.call_activity("submit_candidate_daily", candidate_request)
        if accepted["status"] == "SKIPPED_EXISTING":
            final = result(
                "SKIPPED_EXISTING",
                analysis_date,
                model_purpose,
                selection_run_id=accepted["selection_run_id"],
                candidate_count=accepted["candidate_count"],
            )
            yield from _emit(
                context,
                "pipeline.model.skipped_existing",
                "SKIPPED_EXISTING",
                request=request,
                stage="candidate_submit",
                details=final,
            )
            terminal_email_attempted = True
            email_result = yield from _send_email(
                context,
                request,
                _terminal_email(model_purpose, analysis_date, final),
                stage="terminal",
            )
            _require_email_delivery(email_result)
            return (yield from _finish_model(context, request, final))

        failure_code = "EMAIL_STARTED_FAILED"
        failure_stage = "email"
        started_email = yield from _send_email(
            context,
            request,
            _email(
                _model_subject(model_purpose, analysis_date, "STARTED"),
                {
                    "state": "STARTED",
                    "analysis_date": analysis_date,
                    "model_purpose": model_purpose,
                    "preflight": preflight,
                },
            ),
            stage="started",
        )
        _require_email_delivery(started_email)

        candidate_deadline = context.current_utc_datetime + candidate_timeout
        while True:
            failure_code = "CANDIDATE_POLL_FAILED"
            failure_stage = "candidate_poll"
            candidate_run = yield context.call_activity(
                "candidate_run_status", accepted["process_run_id"]
            )
            if candidate_run["terminal"]:
                break
            if context.current_utc_datetime >= candidate_deadline:
                final = result(
                    "TIMED_OUT",
                    analysis_date,
                    model_purpose,
                    stage="candidate",
                    process_run_id=accepted["process_run_id"],
                    reason="CANDIDATE_POLL_TIMED_OUT",
                )
                terminal_email_attempted = True
                email_result = yield from _send_email(
                    context,
                    request,
                    _terminal_email(model_purpose, analysis_date, final),
                    stage="terminal",
                )
                if _email_delivery_failed(email_result):
                    final["reason"] = "EMAIL_TERMINAL_FAILED"
                return (yield from _finish_model(context, request, final))
            yield context.create_timer(context.current_utc_datetime + poll_interval)

        if candidate_run["status"] != "SUCCEEDED":
            final = result(
                "FAILED",
                analysis_date,
                model_purpose,
                stage="candidate",
                process_run_id=accepted["process_run_id"],
                candidate_status=candidate_run["status"],
                reason="CANDIDATE_RUN_FAILED",
            )
            terminal_email_attempted = True
            email_result = yield from _send_email(
                context,
                request,
                _terminal_email(model_purpose, analysis_date, final),
                stage="terminal",
            )
            if _email_delivery_failed(email_result):
                final["reason"] = "EMAIL_TERMINAL_FAILED"
            return (yield from _finish_model(context, request, final))

        failure_code = "CANDIDATE_FETCH_FAILED"
        failure_stage = "candidate_fetch"
        candidates = yield context.call_activity("fetch_and_verify_candidates", candidate_request)
        if model_purpose == "MEDIUM_20D":
            final = result(
                "SUCCEEDED",
                analysis_date,
                model_purpose,
                stage="parallel_preselection",
                process_run_id=accepted["process_run_id"],
                selection_run_id=candidates[0]["selection_run_id"],
                candidate_count=len(candidates),
                submitted_candidates=0,
            )
            terminal_email_attempted = True
            email_result = yield from _send_email(
                context,
                request,
                _terminal_email(model_purpose, analysis_date, final),
                stage="terminal",
            )
            _require_email_delivery(email_result)
            return (yield from _finish_model(context, request, final))
        failure_code = "PORTAL_SUBMIT_FAILED"
        failure_stage = "portal_submit"
        portal_analysis = yield context.call_activity(
            "submit_portal_candidate_analysis",
            {
                "analysis_date": analysis_date,
                "selection_run_id": candidates[0]["selection_run_id"],
                "model_purpose": model_purpose,
                "candidate_count": len(candidates),
            },
        )
        portal_deadline = context.current_utc_datetime + portal_timeout
        while not portal_analysis["terminal"]:
            if context.current_utc_datetime >= portal_deadline:
                final = result(
                    "TIMED_OUT",
                    analysis_date,
                    model_purpose,
                    stage="portal",
                    process_run_id=accepted["process_run_id"],
                    daily_analysis_id=portal_analysis["daily_analysis_id"],
                    jobs=portal_analysis["jobs"],
                    reason="PORTAL_POLL_TIMED_OUT",
                )
                terminal_email_attempted = True
                email_result = yield from _send_email(
                    context,
                    request,
                    _terminal_email(model_purpose, analysis_date, final),
                    stage="terminal",
                )
                if _email_delivery_failed(email_result):
                    final["reason"] = "EMAIL_TERMINAL_FAILED"
                return (yield from _finish_model(context, request, final))
            yield context.create_timer(context.current_utc_datetime + poll_interval)
            failure_code = "PORTAL_POLL_FAILED"
            failure_stage = "portal_poll"
            portal_analysis = yield context.call_activity(
                "portal_candidate_analysis_status", portal_analysis
            )

        succeeded = portal_analysis["succeeded"]
        failed = portal_analysis["failed"]
        state = "SUCCEEDED" if not failed else "PARTIAL_FAILED" if succeeded else "FAILED"
        final = result(
            state,
            analysis_date,
            model_purpose,
            process_run_id=accepted["process_run_id"],
            selection_run_id=candidates[0]["selection_run_id"],
            daily_analysis_id=portal_analysis["daily_analysis_id"],
            submitted_candidates=len(candidates),
            succeeded=succeeded,
            failed=failed,
            jobs=portal_analysis["jobs"],
            **({"reason": "PORTAL_JOBS_FAILED"} if failed else {}),
        )
        terminal_email_attempted = True
        email_result = yield from _send_email(
            context,
            request,
            _terminal_email(model_purpose, analysis_date, final),
            stage="terminal",
        )
        if _email_delivery_failed(email_result):
            final["state"] = "FAILED"
            final["stage"] = "email"
            final["reason"] = "EMAIL_TERMINAL_FAILED"
        return (yield from _finish_model(context, request, final))
    except Exception:
        if terminal_email_attempted:
            final = result(
                "FAILED",
                analysis_date,
                model_purpose,
                stage="email",
                reason="EMAIL_TERMINAL_FAILED",
            )
            return (yield from _finish_model(context, request, final))
        final = result(
            "FAILED",
            analysis_date,
            model_purpose,
            stage=failure_stage,
            reason=failure_code,
        )
        terminal_email_attempted = True
        try:
            email_result = yield from _send_email(
                context,
                request,
                _terminal_email(model_purpose, analysis_date, final),
                stage="terminal",
            )
            if _email_delivery_failed(email_result):
                final["stage"] = "email"
                final["reason"] = "EMAIL_TERMINAL_FAILED"
        except Exception:
            final["stage"] = "email"
            final["reason"] = "EMAIL_TERMINAL_FAILED"
        return (yield from _finish_model(context, request, final))


WEEKLY_TERMINAL = {"PROMOTED", "REJECTED", "ROLLED_BACK", "FAILED"}


def weekly_model_orchestrator(context: Any) -> Generator[Any, Any, dict[str, Any]]:
    request = context.get_input()
    model_purpose = str(request["model_purpose"])
    iso_week = str(request["iso_week"])
    timeout = timedelta(minutes=int(request["timeout_minutes"]))
    poll_interval = timedelta(seconds=int(request["poll_seconds"]))
    weekly_run_id: str | None = None
    try:
        accepted = yield context.call_activity(
            "submit_weekly_training",
            {"iso_week": iso_week, "model_purpose": model_purpose},
        )
        weekly_run_id = str(accepted["weekly_run_id"])
        if accepted["status"] in WEEKLY_TERMINAL:
            run_status = accepted
        else:
            started = yield context.call_activity(
                "start_weekly_training_job",
                {"weekly_run_id": weekly_run_id, "model_purpose": model_purpose},
            )
            deadline = context.current_utc_datetime + timeout
            while True:
                job = yield context.call_activity(
                    "weekly_training_job_status", started["execution_name"]
                )
                if job["terminal"]:
                    if not job["succeeded"]:
                        return {
                            "state": "FAILED",
                            "stage": "training_job",
                            "iso_week": iso_week,
                            "model_purpose": model_purpose,
                            "weekly_run_id": weekly_run_id,
                        }
                    break
                if context.current_utc_datetime >= deadline:
                    return {
                        "state": "TIMED_OUT",
                        "stage": "training_job",
                        "iso_week": iso_week,
                        "model_purpose": model_purpose,
                        "weekly_run_id": weekly_run_id,
                    }
                yield context.create_timer(context.current_utc_datetime + poll_interval)

            while True:
                run_status = yield context.call_activity(
                    "weekly_training_status", weekly_run_id
                )
                if run_status["status"] in WEEKLY_TERMINAL:
                    break
                if context.current_utc_datetime >= deadline:
                    return {
                        "state": "TIMED_OUT",
                        "stage": "promotion",
                        "iso_week": iso_week,
                        "model_purpose": model_purpose,
                        "weekly_run_id": weekly_run_id,
                    }
                yield context.create_timer(context.current_utc_datetime + poll_interval)

        if run_status["status"] == "PROMOTED":
            smoke = yield context.call_activity("weekly_activation_smoke", weekly_run_id)
            if not smoke["passed"]:
                return {
                    "state": "FAILED",
                    "stage": "activation_smoke",
                    "iso_week": iso_week,
                    "model_purpose": model_purpose,
                    "weekly_run_id": weekly_run_id,
                }
            state = "SUCCEEDED"
        elif run_status["status"] == "REJECTED":
            state = "REJECTED"
        else:
            state = "FAILED"
        return {
            "state": state,
            "iso_week": iso_week,
            "model_purpose": model_purpose,
            "weekly_run_id": weekly_run_id,
            "status": run_status["status"],
        }
    except Exception:
        return {
            "state": "FAILED",
            "stage": "orchestrator",
            "iso_week": iso_week,
            "model_purpose": model_purpose,
            "weekly_run_id": weekly_run_id,
        }


def weekly_parent_orchestrator(context: Any) -> Generator[Any, Any, dict[str, Any]]:
    request = context.get_input()
    iso_week = str(request["iso_week"])
    eligibility = yield context.call_activity("weekly_eligibility", None)
    if not eligibility["eligible"]:
        return {
            "state": "SKIPPED",
            "iso_week": iso_week,
            "reason": eligibility.get("reason", "NOT_ELIGIBLE"),
            "models": {},
        }
    models: dict[str, dict[str, Any]] = {}
    for model_purpose in MODEL_SEQUENCE:
        child_result = yield context.call_sub_orchestrator(
            "weekly_model_orchestrator",
            {
                "iso_week": iso_week,
                "model_purpose": model_purpose,
                "timeout_minutes": request["timeout_minutes"],
                "poll_seconds": request["poll_seconds"],
            },
            request["child_instance_ids"][model_purpose],
        )
        models[model_purpose] = child_result
    states = {item["state"] for item in models.values()}
    state = "SUCCEEDED" if states <= {"SUCCEEDED", "REJECTED"} else "FAILED"
    return {"state": state, "iso_week": iso_week, "models": models}
