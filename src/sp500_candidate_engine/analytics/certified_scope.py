"""Conservative, issuer-level scopes for certified historical input projections."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import unquote, urlparse

import pandas as pd

from sp500_candidate_engine.database import _canonical_hash

DATASET_CODE = "historical_certified_subset_v1"
SCOPE_VERSION = "certified-historical-eligible-scope-v1"


class CertifiedScopeError(ValueError):
    pass


@dataclass(frozen=True)
class IssuerQuarantine:
    excluded_issuer_ids: frozenset[uuid.UUID]
    admitted_action_ids: frozenset[uuid.UUID]
    excluded_action_ids: frozenset[uuid.UUID]
    certified_action_ids: frozenset[uuid.UUID]
    proof_matrix_sha256: str
    quality_mask_sha256: str
    reasons: Mapping[str, tuple[str, ...]]


def issuer_quarantine(
    *, matrix: Mapping[str, object], actions: tuple[Mapping[str, object], ...],
    matrix_sha256: str,
) -> IssuerQuarantine:
    """Decide from proof status/identity only, never from prices, labels or scores."""
    rows = matrix.get("rows")
    if not isinstance(rows, list):
        raise CertifiedScopeError("Proof matrix rows are required")
    by_id = {str(action["action_id"]): action for action in actions}
    if (
        len(by_id) != len(actions)
        or len(rows) != len(actions)
        or {str(row["action_id"]) for row in rows} != set(by_id)
    ):
        raise CertifiedScopeError("Every original action must be accounted for exactly once")
    reasons: dict[str, list[str]] = {}
    certified = set()
    for row in rows:
        action = by_id[str(row["action_id"])]
        if row.get("certified") is True:
            certified.add(uuid.UUID(str(action["action_id"])))
        elif row.get("certified") is False:
            reasons.setdefault(str(action["issuer_id"]), []).append(
                f"{row['action_id']}:{row['status']}",
            )
        else:
            raise CertifiedScopeError("Proof status must be explicit")
    excluded = frozenset(uuid.UUID(value) for value in reasons)
    admitted_actions = frozenset(
        uuid.UUID(str(action["action_id"])) for action in actions
        if uuid.UUID(str(action["issuer_id"])) not in excluded
    )
    if not admitted_actions <= certified:
        raise CertifiedScopeError("An uncertified action would remain in the admitted scope")
    excluded_actions = frozenset(uuid.UUID(key) for key in by_id) - admitted_actions
    normalized_reasons = {key: tuple(sorted(value)) for key, value in sorted(reasons.items())}
    mask_hash = _canonical_hash({
        "version": SCOPE_VERSION, "proof_matrix_sha256": matrix_sha256,
        "excluded_issuers": sorted(str(value) for value in excluded),
        "reasons": normalized_reasons,
    })
    return IssuerQuarantine(
        excluded, admitted_actions, excluded_actions, frozenset(certified),
        matrix_sha256, mask_hash, normalized_reasons,
    )


def verify_split_proof(
    *, row: Mapping[str, object], action: Mapping[str, object], cutoff_at: datetime,
    document_path: Path, accepted_at: datetime,
) -> datetime:
    """A real source publication bound is not the projection's creation timestamp."""
    proof = row.get("proof")
    if row.get("certified") is not True or not isinstance(proof, dict):
        raise CertifiedScopeError("A certified immutable-source proof is required")
    available = datetime.fromisoformat(str(proof["publication_version_bound"]))
    if available.utcoffset() is None or available != accepted_at or available > cutoff_at:
        raise CertifiedScopeError("Unverified or future source publication bound")
    if str(row["action_id"]) != str(action["action_id"]):
        raise CertifiedScopeError("Proof action identity mismatch")
    if (
        str(row["stored_execution_session"]) != str(action["effective_date"])
        or Decimal(str(row["stored_split_from"])) != Decimal(str(action["split_from"]))
        or Decimal(str(row["stored_split_to"])) != Decimal(str(action["split_to"]))
        or row["stored_payload_hash"] != action["payload_hash"]
    ):
        raise CertifiedScopeError("Proof facts differ from the immutable original row")
    source = urlparse(str(proof["url"]))
    if (
        source.scheme != "https" or source.hostname != "www.sec.gov"
        or f"/Archives/edgar/data/{int(str(action['cik']))}/" not in source.path
        or proof.get("provider_historical_revision_claim") is not False
    ):
        raise CertifiedScopeError("Proof must bind the original SEC issuer/version")
    if hashlib.sha256(document_path.read_bytes()).hexdigest() != proof["document_sha256"]:
        raise CertifiedScopeError("Immutable document/prefix checksum mismatch")
    return available


def retained_instruments(
    owners: Mapping[uuid.UUID, uuid.UUID], quarantine: IssuerQuarantine,
) -> frozenset[uuid.UUID]:
    return frozenset(
        instrument for instrument, issuer in owners.items()
        if issuer not in quarantine.excluded_issuer_ids
    )


def expected_test_index(
    *, membership: Mapping[pd.Timestamp, set[str]], calendar: tuple[pd.Timestamp, ...],
    start: pd.Timestamp, end: pd.Timestamp, horizon_sessions: int,
) -> pd.MultiIndex:
    """Maturity uses the calendar; unknown/excluded label values are never computed."""
    records = []
    for position, session in enumerate(calendar):
        exit_position = position + horizon_sessions
        if (
            start <= session <= end and exit_position < len(calendar)
            and calendar[exit_position] <= end
        ):
            records.extend((session, symbol) for symbol in sorted(membership.get(session, set())))
    return pd.MultiIndex.from_tuples(records, names=["datetime", "instrument"])


def coverage_accounting(
    *, observations: int, expected_index: pd.MultiIndex, original_reference_count: int,
) -> dict[str, object]:
    if original_reference_count < 1 or observations < 0 or not len(expected_index):
        raise CertifiedScopeError("Nonempty original membership/reference is required")
    date_counts = pd.Series(1, index=expected_index).groupby(level="datetime").sum()
    denominator = int(date_counts.clip(lower=original_reference_count).sum())
    if observations > len(expected_index):
        raise CertifiedScopeError("Scored rows exceed original point-in-time membership")
    return {
        "coverage": observations / denominator,
        "coverage_original_membership_slots": len(expected_index),
        "coverage_original_reference_population": original_reference_count,
        "coverage_applied_denominator": denominator,
        "coverage_scored_observations": observations,
        "coverage_basis": "ORIGINAL_PIT_MEMBERSHIP_WITH_UNSHRUNK_REFERENCE_FLOOR",
    }


def _file_uri(uri: str) -> Path:
    parsed = urlparse(uri)
    if (
        parsed.scheme != "file" or parsed.netloc not in {"", "localhost"}
        or parsed.query or parsed.fragment
    ):
        raise CertifiedScopeError("Certified scope must use an explicit retained local artifact")
    value = unquote(parsed.path)
    if len(value) >= 3 and value[0] in {"/", "\\"} and value[2] == ":":
        value = value[1:]
    return Path(value)


def read_scope_artifact(
    *, uri: str, expected_sha256: str, cutoff_at: datetime,
) -> dict[str, object]:
    manifest_path = _file_uri(uri).resolve()
    content = manifest_path.read_bytes()
    if hashlib.sha256(content).hexdigest() != expected_sha256:
        raise CertifiedScopeError("Certified input artifact checksum mismatch")
    payload = json.loads(content)
    scope = payload["scope"]
    if (
        payload["schema_version"] != SCOPE_VERSION
        or payload["knowledge_mode"] != "HISTORICAL_RECONSTRUCTION"
        or datetime.fromisoformat(payload["cutoff_at"]) != cutoff_at
        or datetime.fromisoformat(payload["data_publication_max"]) > cutoff_at
        or datetime.fromisoformat(payload["generated_at"]) <= cutoff_at
        or scope["original_reference_count"] != 503
        or scope["original_membership_preserved"] is not True
        or scope["completeness"] != "CERTIFIED_ELIGIBLE_SCOPE_ONLY"
    ):
        raise CertifiedScopeError("Certified input clocks/scope contract mismatch")
    original = set(scope["original_current_instrument_ids"])
    excluded = set(scope["quarantined_current_instrument_ids"])
    eligible = set(scope["eligible_current_instrument_ids"])
    if (
        len(original) != 503 or excluded & eligible
        or excluded | eligible != original
        or len(original) != len(scope["original_current_instrument_ids"])
    ):
        raise CertifiedScopeError("Quality eligibility must not rewrite original membership")
    for artifact in payload["artifacts"].values():
        path = _file_uri(artifact["uri"]).resolve()
        if not path.is_relative_to(manifest_path.parent):
            raise CertifiedScopeError("Input component must remain in the immutable bundle")
        if hashlib.sha256(path.read_bytes()).hexdigest() != artifact["sha256"]:
            raise CertifiedScopeError("Certified input component checksum mismatch")
    return {
        **scope, "input_artifact_sha256": expected_sha256,
        "data_publication_max": payload["data_publication_max"],
    }


def read_context_scope(
    connection: object, execution_context_id: uuid.UUID,
) -> dict[str, object] | None:
    rows = connection.execute(  # type: ignore[attr-defined]
        """
        SELECT snapshot.storage_uri,snapshot.content_hash,snapshot.source_available_at,
               context.cutoff_at,context.knowledge_mode
        FROM ops.execution_context context
        JOIN ops.input_manifest_member member USING(input_manifest_id)
        JOIN ops.source_snapshot snapshot USING(source_snapshot_id)
        WHERE context.execution_context_id=%s AND member.dataset_code=%s
        """,
        (execution_context_id, DATASET_CODE),
    ).fetchall()
    if not rows:
        return None
    if len(rows) != 1 or rows[0]["knowledge_mode"] != "HISTORICAL_RECONSTRUCTION":
        raise CertifiedScopeError("Certified subsets require one explicit reconstruction scope")
    row = rows[0]
    scope = read_scope_artifact(
        uri=row["storage_uri"], expected_sha256=row["content_hash"], cutoff_at=row["cutoff_at"],
    )
    if row["source_available_at"] != datetime.fromisoformat(scope["data_publication_max"]):
        raise CertifiedScopeError("Snapshot bound must equal the certified data publication bound")
    return scope
