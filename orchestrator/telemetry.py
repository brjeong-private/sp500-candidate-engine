"""Emit allowlisted structured telemetry through the Functions logging pipeline."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

LOGGER = logging.getLogger("candidate_pipeline.telemetry")
SAFE_FIELDS = frozenset(
    {
        "event",
        "parent_instance_id",
        "model_instance_id",
        "target_session",
        "model_purpose",
        "candidate_process_run_id",
        "selection_run_id",
        "daily_analysis_id",
        "state",
        "stage",
        "remediated",
    }
)


def emit_pipeline_telemetry(
    payload: dict[str, Any],
    *,
    logger: logging.Logger = LOGGER,
) -> dict[str, Any]:
    """Log one safe JSON trace for Application Insights and Log Analytics."""
    safe = {
        key: value
        for key, value in payload.items()
        if key in SAFE_FIELDS and value is not None and isinstance(value, (str, int, bool))
    }
    if not isinstance(safe.get("event"), str) or not isinstance(safe.get("state"), str):
        raise ValueError("telemetry requires string event and state")
    safe["timestamp"] = datetime.now(UTC).isoformat()
    logger.info(json.dumps(safe, sort_keys=True, separators=(",", ":")))
    return safe
