"""외부 I/O 없이 Durable 작업과 타이머만 예약하는 결정적 흐름."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import suppress
from datetime import timedelta
from typing import Any


def result(state: str, analysis_date: str, **details: Any) -> dict[str, Any]:
    return {"state": state, "analysis_date": analysis_date, **details}


def _email(subject: str, body: dict[str, Any]) -> dict[str, str]:
    return {"subject": subject, "body": str(body)}


def daily_orchestrator(context: Any) -> Generator[Any, Any, dict[str, Any]]:
    request = context.get_input()
    analysis_date = str(request["analysis_date"])
    candidate_timeout = timedelta(minutes=int(request["candidate_timeout_minutes"]))
    portal_timeout = timedelta(minutes=int(request["portal_timeout_minutes"]))
    poll_interval = timedelta(seconds=int(request["poll_seconds"]))

    try:
        session = yield context.call_activity("check_exchange_session", analysis_date)
        if not session["is_session"]:
            return result(
                "SUCCEEDED",
                analysis_date,
                skipped=True,
                reason="not_exchange_session",
            )

        yield context.call_activity("readiness_preflight", None)
        yield context.call_activity(
            "send_email",
            _email(
                f"[candidate-orchestrator] {analysis_date} started",
                {"state": "STARTED", "analysis_date": analysis_date},
            ),
        )
        accepted = yield context.call_activity("submit_candidate_daily", analysis_date)
        candidate_deadline = context.current_utc_datetime + candidate_timeout
        while True:
            candidate_run = yield context.call_activity(
                "candidate_run_status", accepted["process_run_id"]
            )
            if candidate_run["terminal"]:
                break
            if context.current_utc_datetime >= candidate_deadline:
                final = result(
                    "TIMED_OUT",
                    analysis_date,
                    stage="candidate",
                    process_run_id=accepted["process_run_id"],
                )
                yield context.call_activity(
                    "send_email",
                    _email(f"[candidate-orchestrator] {analysis_date} TIMED_OUT", final),
                )
                return final
            yield context.create_timer(context.current_utc_datetime + poll_interval)

        if candidate_run["status"] != "SUCCEEDED":
            final = result(
                "FAILED",
                analysis_date,
                stage="candidate",
                process_run_id=accepted["process_run_id"],
                candidate_status=candidate_run["status"],
                reason=candidate_run.get("failure_reason"),
            )
            yield context.call_activity(
                "send_email",
                _email(f"[candidate-orchestrator] {analysis_date} FAILED", final),
            )
            return final

        candidates = yield context.call_activity("fetch_and_verify_candidates", analysis_date)
        portal_analysis = yield context.call_activity(
            "submit_portal_candidate_analysis",
            {
                "analysis_date": analysis_date,
                "selection_run_id": candidates[0]["selection_run_id"],
                "model_purpose": candidates[0]["model_purpose"],
                "candidate_count": len(candidates),
            },
        )
        portal_deadline = context.current_utc_datetime + portal_timeout
        while not portal_analysis["terminal"]:
            if context.current_utc_datetime >= portal_deadline:
                final = result(
                    "TIMED_OUT",
                    analysis_date,
                    stage="portal",
                    process_run_id=accepted["process_run_id"],
                    daily_analysis_id=portal_analysis["daily_analysis_id"],
                    jobs=portal_analysis["jobs"],
                )
                yield context.call_activity(
                    "send_email",
                    _email(f"[candidate-orchestrator] {analysis_date} TIMED_OUT", final),
                )
                return final
            yield context.create_timer(context.current_utc_datetime + poll_interval)
            portal_analysis = yield context.call_activity(
                "portal_candidate_analysis_status", portal_analysis
            )

        succeeded = portal_analysis["succeeded"]
        failed = portal_analysis["failed"]
        state = "SUCCEEDED" if not failed else "PARTIAL_FAILED" if succeeded else "FAILED"
        final = result(
            state,
            analysis_date,
            process_run_id=accepted["process_run_id"],
            daily_analysis_id=portal_analysis["daily_analysis_id"],
            submitted_candidates=len(candidates),
            succeeded=succeeded,
            failed=failed,
            jobs=portal_analysis["jobs"],
        )
        yield context.call_activity(
            "send_email",
            _email(f"[candidate-orchestrator] {analysis_date} {state}", final),
        )
        return final
    except Exception as error:
        final = result(
            "FAILED",
            analysis_date,
            stage="orchestrator",
            reason=type(error).__name__,
        )
        with suppress(Exception):
            yield context.call_activity(
                "send_email",
                _email(f"[candidate-orchestrator] {analysis_date} FAILED", final),
            )
        return final
