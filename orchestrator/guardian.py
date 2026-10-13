"""15분 간격으로 배포 리소스의 안전한 준비 상태를 복원한다."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from clients import readiness_preflight, send_email
from telemetry import emit_pipeline_telemetry

LOGGER = logging.getLogger(__name__)


def _emit_safely(
    telemetry: Callable[[dict[str, Any]], dict[str, Any]],
    payload: dict[str, Any],
) -> None:
    try:
        telemetry(payload)
    except Exception:
        LOGGER.warning("pipeline telemetry emission failed")


def _safe_success(preflight: dict[str, str]) -> dict[str, object]:
    remediated = preflight.get("remediated", "none")
    return {
        "event": "resource_guardian.completed",
        "state": "SUCCEEDED",
        "status": preflight.get("status", "unknown"),
        "checked": [item for item in preflight.get("checked", "").split(",") if item],
        "remediated": (
            [] if remediated == "none" else [item for item in remediated.split(",") if item]
        ),
    }


def _failure_result(error: Exception, *, alert_sent: bool) -> dict[str, object]:
    return {
        "event": "resource_guardian.failed",
        "state": "FAILED",
        "reason": type(error).__name__,
        "alert_sent": alert_sent,
    }


def run_guardian(
    *,
    preflight: Callable[[], dict[str, str]] = readiness_preflight,
    email_client: Callable[[dict[str, Any]], dict[str, Any]] = send_email,
    telemetry: Callable[[dict[str, Any]], dict[str, Any]] = emit_pipeline_telemetry,
    logger: logging.Logger = LOGGER,
) -> dict[str, object]:
    """Run the existing safe preflight/remediation contract and alert on failure."""
    _emit_safely(
        telemetry,
        {
            "event": "pipeline.guardian.started",
            "state": "STARTED",
            "stage": "guardian",
            "remediated": False,
        },
    )
    try:
        result = _safe_success(preflight())
    except Exception as error:
        alert = {
            "subject": "[candidate-orchestrator] resource guardian FAILED",
            "body": json.dumps(
                {
                    "state": "FAILED",
                    "component": "resource_guardian",
                    "reason": type(error).__name__,
                },
                sort_keys=True,
            ),
        }
        alert_sent = False
        try:
            alert_sent = email_client(alert).get("sent") is True
        except Exception:
            alert_sent = False
        _emit_safely(
            telemetry,
            {
                "event": "pipeline.email.terminal",
                "state": "SUCCEEDED" if alert_sent else "FAILED",
                "stage": "guardian_alert",
                "remediated": False,
            },
        )
        _emit_safely(
            telemetry,
            {
                "event": "pipeline.guardian.terminal",
                "state": "FAILED",
                "stage": "guardian",
                "remediated": False,
            },
        )
        logger.error(json.dumps(_failure_result(error, alert_sent=alert_sent), sort_keys=True))
        raise

    remediated = bool(result["remediated"])
    if remediated:
        _emit_safely(
            telemetry,
            {
                "event": "pipeline.guardian.remediation",
                "state": "SUCCEEDED",
                "stage": "guardian",
                "remediated": True,
            },
        )
    _emit_safely(
        telemetry,
        {
            "event": "pipeline.guardian.terminal",
            "state": "SUCCEEDED",
            "stage": "guardian",
            "remediated": remediated,
        },
    )
    logger.info(json.dumps(result, sort_keys=True))
    return result
