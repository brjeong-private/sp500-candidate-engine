from __future__ import annotations

import math
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

from sp500_candidate_engine.analytics.adjustments import AdjustmentError, validated_split_ratios
from sp500_candidate_engine.analytics.source_repository import SourceRepository
from sp500_candidate_engine.production_models import CorporateAction


def _number(value: object) -> float:
    if not isinstance(value, (int, float, Decimal)) or isinstance(value, bool):
        raise TypeError("Selection price/action value must be numeric")
    return float(value)


def read_selection_eligibility(
    repository: SourceRepository, *, execution_context_id: uuid.UUID, target_session: date
) -> tuple[list[dict[str, object]], dict[uuid.UUID, tuple[str, ...]]]:
    repository.validate_context_manifest(execution_context_id=execution_context_id)
    members = repository.read_universe_members(
        execution_context_id=execution_context_id, target_session=target_session
    )
    bars = repository.read_bars(
        execution_context_id=execution_context_id,
        start_date=target_session, end_date=target_session,
    )
    issues = repository.read_blocking_issues(execution_context_id=execution_context_id)
    aliases = [value for member in members
               for value in (str(member["instrument_id"]), str(member["symbol"]))]
    unmapped_blocking = any(
        issue["entity_key"] and not any(
            str(issue["entity_key"]) == value or str(issue["entity_key"]).startswith(value + ":")
            for value in aliases
        )
        for issue in issues
    )
    gate_reasons = {}
    for member in members:
        instrument_id = uuid.UUID(str(member["instrument_id"]))
        reasons: list[str] = []
        if unmapped_blocking:
            reasons.append("UNMAPPED_BLOCKING_QUALITY_ISSUE")
        selected_bars = [bar for bar in bars if str(bar["instrument_id"]) == str(instrument_id)]
        if not selected_bars:
            reasons.append("MISSING_TARGET_PRICE")
        signatures = set()
        for bar in selected_bars:
            values = [_number(bar[key]) for key in ("open", "high", "low", "close")]
            volume = bar["volume"]
            if (
                not all(math.isfinite(value) and value > 0 for value in values)
                or not values[2] <= values[0] <= values[1]
                or not values[2] <= values[3] <= values[1]
                or type(volume) is not int or volume < 0
                or bar.get("price_adjustment_status", "UNKNOWN") == "UNKNOWN"
                or bar.get("volume_adjustment_status", "UNKNOWN") == "UNKNOWN"
            ):
                reasons.append("INVALID_TARGET_PRICE")
            signatures.add(tuple(values))
        if len(signatures) > 1:
            reasons.append("AMBIGUOUS_TARGET_PRICE")
        for issue in issues:
            key = str(issue["entity_key"] or "")
            member_aliases = (str(instrument_id), str(member["symbol"]))
            if not key or any(
                key == alias or key.startswith(alias + ":") for alias in member_aliases
            ):
                reasons.append("BLOCKING_QUALITY_ISSUE")
        actions = repository.read_corporate_actions(
            execution_context_id=execution_context_id, instrument_id=instrument_id,
            start_date=target_session - timedelta(days=365), end_date=target_session,
        )
        splits = []
        for action in actions:
            if action["action_type"] != "SPLIT":
                continue
            effective, available = action["effective_date"], action["source_available_at"]
            if not isinstance(effective, date) or not isinstance(available, datetime):
                reasons.append("INVALID_ACTION_LINEAGE")
                continue
            splits.append(CorporateAction(
                str(action["action_id"]), str(member["symbol"]), "SPLIT", effective,
                None, None, None, None, None,
                _number(action["split_from"]) if action["split_from"] is not None else None,
                _number(action["split_to"]) if action["split_to"] is not None else None,
                available, {},
            ))
        try:
            validated_split_ratios(tuple(splits))
        except AdjustmentError:
            reasons.append("INVALID_ACTION_LINEAGE")
        gate_reasons[instrument_id] = tuple(sorted(set(reasons)))
    return members, gate_reasons
