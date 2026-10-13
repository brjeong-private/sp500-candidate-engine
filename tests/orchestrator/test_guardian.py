from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

import pytest

ORCHESTRATOR_ROOT = Path(__file__).resolve().parents[2] / "orchestrator"
sys.path.insert(0, str(ORCHESTRATOR_ROOT))

import function_app  # noqa: E402
import guardian  # noqa: E402


class RecordingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def _logger() -> tuple[logging.Logger, RecordingHandler]:
    logger = logging.Logger("test.resource_guardian")
    handler = RecordingHandler()
    logger.addHandler(handler)
    return logger, handler


def test_guardian_timer_runs_every_fifteen_minutes():
    try:
        timer = next(
            item
            for item in function_app.app.get_functions()
            if item.get_function_name() == "resource_guardian_timer"
        )
        trigger = next(
            binding
            for binding in timer.get_dict_repr()["bindings"]
            if binding["type"] == "timerTrigger"
        )

        assert trigger["schedule"] == "0 */15 * * * *"
        assert trigger["runOnStartup"] is False
        assert trigger["useMonitor"] is True
    finally:
        function_app.app.functions_bindings.clear()


def test_guardian_logs_only_safe_success_summary():
    logger, handler = _logger()

    result = guardian.run_guardian(
        preflight=lambda: {
            "status": "ready",
            "checked": (
                "candidate,candidate_postgresql,portal,portal_mysql,"
                "orchestrator_storage,tradingagents"
            ),
            "remediated": "candidate_app:start,tradingagents:min_replicas",
        },
        email_client=lambda payload: pytest.fail(f"unexpected email: {payload}"),
        logger=logger,
    )

    assert result == {
        "event": "resource_guardian.completed",
        "state": "SUCCEEDED",
        "status": "ready",
        "checked": [
            "candidate",
            "candidate_postgresql",
            "portal",
            "portal_mysql",
            "orchestrator_storage",
            "tradingagents",
        ],
        "remediated": ["candidate_app:start", "tradingagents:min_replicas"],
    }
    assert json.loads(handler.messages[0]) == result
    assert "/subscriptions/" not in handler.messages[0]


def test_guardian_alerts_logs_and_reraises_preflight_failure():
    logger, handler = _logger()
    alerts: list[dict[str, Any]] = []

    def fail_preflight() -> dict[str, str]:
        raise RuntimeError("sensitive raw response")

    def send_alert(payload: dict[str, Any]) -> dict[str, Any]:
        alerts.append(payload)
        return {"sent": True, "id": "not-logged"}

    with pytest.raises(RuntimeError, match="sensitive raw response"):
        guardian.run_guardian(
            preflight=fail_preflight,
            email_client=send_alert,
            logger=logger,
        )

    assert alerts == [
        {
            "subject": "[candidate-orchestrator] resource guardian FAILED",
            "body": (
                '{"component": "resource_guardian", "reason": "RuntimeError", "state": "FAILED"}'
            ),
        }
    ]
    logged = json.loads(handler.messages[0])
    assert logged == {
        "alert_sent": True,
        "event": "resource_guardian.failed",
        "reason": "RuntimeError",
        "state": "FAILED",
    }
    assert "sensitive raw response" not in handler.messages[0]


def test_guardian_still_fails_when_alert_delivery_fails():
    logger, handler = _logger()

    def fail_preflight() -> dict[str, str]:
        raise ValueError("preflight failed")

    def fail_email(payload: dict[str, Any]) -> dict[str, Any]:
        del payload
        raise ConnectionError("email failed")

    with pytest.raises(ValueError, match="preflight failed"):
        guardian.run_guardian(
            preflight=fail_preflight,
            email_client=fail_email,
            logger=logger,
        )

    assert json.loads(handler.messages[0])["alert_sent"] is False
