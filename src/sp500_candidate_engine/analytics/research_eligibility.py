"""Explicit research eligibility, never reconstructed official listing-state history."""

from __future__ import annotations

import math
import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sp500_candidate_engine.analytics.certified_scope import DATASET_CODE, read_scope_artifact
from sp500_candidate_engine.backfill import backfill_cutoff

if TYPE_CHECKING:
    from sp500_candidate_engine.analytics.source_repository import SourceRepository

POLICY_VERSION = "historical-membership-price-research-v1"
CLASSIFICATION = "EXPERIMENTAL_RESEARCH_ELIGIBILITY"


def research_members(
    *, members: list[dict[str, object]], bars: list[dict[str, object]],
    scope: dict[str, object], target_session: date, cutoff_at: datetime,
    snapshot_id: uuid.UUID,
) -> list[dict[str, object]]:
    policy = scope.get("research_eligibility")
    if (
        not isinstance(policy, dict) or policy.get("policy_version") != POLICY_VERSION
        or policy.get("classification") != CLASSIFICATION
        or policy.get("target_session") != str(target_session)
        or policy.get("official_historical_state_verified") is not False
        or cutoff_at != backfill_cutoff(target_session)
        or {str(m["instrument_id"]) for m in members}
        != set(scope["original_current_instrument_ids"])
        or len(members) != scope["original_reference_count"]
        or any(
            str(m["universe_version_id"]) != scope["universe_version_id"]
            or m["universe_source_available_at"] > cutoff_at
            or m["announced_at"] > cutoff_at or m["effective_at"] > cutoff_at
            for m in members
        )
    ):
        raise ValueError("Research membership/policy/cutoff binding mismatch")
    excluded = set(scope["quarantined_current_instrument_ids"])
    prices: dict[str, list[dict[str, object]]] = {}
    for bar in bars:
        key = str(bar["instrument_id"])
        if (
            bar["session_date"] != target_session
            or bar["source_available_at"] > cutoff_at
            or key in excluded
        ):
            raise ValueError("Research target price violates temporal/quarantine boundary")
        prices.setdefault(key, []).append(bar)
    result = []
    for member in members:
        key = str(member["instrument_id"])
        selected = prices.get(key, [])
        reasons = []
        if key in excluded:
            reasons.append("CERTIFIED_SCOPE_ISSUER_QUARANTINE")
        if not selected:
            reasons.append("MISSING_RESEARCH_TARGET_PRICE")
        signatures = set()
        for bar in selected:
            values = tuple(float(bar[name]) for name in ("open", "high", "low", "close"))
            if (
                bar["price_adjustment_status"] != "UNADJUSTED"
                or bar["volume_adjustment_status"] != "UNADJUSTED"
                or not all(math.isfinite(v) and v > 0 for v in values)
                or not values[2] <= values[0] <= values[1]
                or not values[2] <= values[3] <= values[1]
                or type(bar["volume"]) is not int or bar["volume"] < 0
            ):
                reasons.append("INVALID_RESEARCH_TARGET_PRICE")
            signatures.add(values)
        if len(signatures) > 1:
            reasons.append("AMBIGUOUS_RESEARCH_TARGET_PRICE")
        result.append({
            **member, "primary_exchange": None, "instrument_status": None,
            "eligibility_policy": POLICY_VERSION, "eligibility_classification": CLASSIFICATION,
            "official_historical_state_verified": False,
            "research_gate_reasons": tuple(sorted(set(reasons))),
            "research_eligibility_snapshot_id": snapshot_id,
            "research_information_available_at": datetime.fromisoformat(
                scope["data_publication_max"],
            ),
            "research_generated_at": datetime.fromisoformat(scope["generated_at"]),
        })
    return result


def read_research_members(
    repository: SourceRepository, *, execution_context_id: uuid.UUID, target_session: date,
) -> list[dict[str, object]] | None:
    rows = repository.connection.execute(
        """
        SELECT ec.knowledge_mode,ec.cutoff_at,ss.source_snapshot_id,ss.storage_uri,
               ss.content_hash,ss.source_available_at,ss.coverage_end
        FROM ops.execution_context ec
        LEFT JOIN ops.input_manifest_member imm
          ON imm.input_manifest_id=ec.input_manifest_id AND imm.dataset_code=%s
        LEFT JOIN ops.source_snapshot ss USING(source_snapshot_id)
        WHERE ec.execution_context_id=%s AND ec.config_version=%s
        """,
        (DATASET_CODE, execution_context_id, POLICY_VERSION),
    ).fetchall()
    if not rows:
        return None
    if (
        len(rows) != 1 or rows[0]["knowledge_mode"] != "HISTORICAL_RECONSTRUCTION"
        or rows[0]["source_snapshot_id"] is None
        or rows[0]["coverage_end"] != target_session
    ):
        raise ValueError("Research eligibility requires one explicit DAILY reconstruction scope")
    row = rows[0]
    scope = read_scope_artifact(
        uri=row["storage_uri"], expected_sha256=row["content_hash"], cutoff_at=row["cutoff_at"],
    )
    if row["source_available_at"] != datetime.fromisoformat(scope["data_publication_max"]):
        raise ValueError("Research source publication binding mismatch")
    future = repository.connection.execute(
        """
        SELECT ss.source_snapshot_id FROM ops.execution_context ec
        JOIN ops.input_manifest_member imm USING(input_manifest_id)
        JOIN ops.source_snapshot ss USING(source_snapshot_id)
        WHERE ec.execution_context_id=%s
          AND (ss.source_available_at>ec.cutoff_at OR ss.coverage_end>%s)
        LIMIT 1
        """,
        (execution_context_id, target_session),
    ).fetchall()
    if future:
        raise ValueError("Research manifest contains future source/coverage")
    members = repository.connection.execute(
        """
        WITH eligible_versions AS (
            SELECT uv.*,ss.source_available_at,
              row_number() OVER(ORDER BY uv.effective_at DESC,uv.as_of_date DESC,
                                        uv.universe_version_id DESC) AS chosen
            FROM ops.execution_context ec
            JOIN ops.input_manifest_member imm USING(input_manifest_id)
            JOIN ops.source_snapshot ss USING(source_snapshot_id)
            JOIN ref.universe_version uv USING(source_snapshot_id)
            WHERE ec.execution_context_id=%s AND uv.as_of_date<=%s
              AND uv.announced_at<=ec.cutoff_at AND uv.effective_at<=ec.cutoff_at
              AND ss.source_available_at<=ec.cutoff_at
        )
        SELECT um.instrument_id,i.issuer_id,um.symbol,um.security_name,um.sector,um.sub_industry,
               uv.universe_version_id,uv.source_snapshot_id AS universe_snapshot_id,
               uv.source_available_at AS universe_source_available_at,
               uv.announced_at,uv.effective_at
        FROM eligible_versions uv
        JOIN ref.universe_member um USING(universe_version_id)
        JOIN ref.instrument i USING(instrument_id)
        WHERE uv.chosen=1 ORDER BY um.instrument_id
        """,
        (execution_context_id, target_session),
    ).fetchall()
    return research_members(
        members=members, bars=repository.read_bars(
            execution_context_id=execution_context_id,
            start_date=target_session, end_date=target_session,
        ), scope=scope, target_session=target_session, cutoff_at=row["cutoff_at"],
        snapshot_id=row["source_snapshot_id"],
    )
