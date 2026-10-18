import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from sp500_candidate_engine.analytics.certified_scope import (
    SCOPE_VERSION,
    CertifiedScopeError,
    coverage_accounting,
    expected_test_index,
    issuer_quarantine,
    read_scope_artifact,
    retained_instruments,
    verify_split_proof,
)


def test_whole_issuer_exclusion_also_removes_its_certified_action_and_share_classes() -> None:
    issuer_a, issuer_b = uuid.uuid4(), uuid.uuid4()
    action_ids = [uuid.uuid4() for _ in range(3)]
    actions = tuple(
        {"action_id": str(action), "issuer_id": str(issuer_a if index < 2 else issuer_b)}
        for index, action in enumerate(action_ids)
    )
    matrix = {"rows": [
        {"action_id": str(action_ids[0]), "certified": True, "status": "CERTIFIED"},
        {"action_id": str(action_ids[1]), "certified": False, "status": "UNKNOWN_VERSION"},
        {"action_id": str(action_ids[2]), "certified": True, "status": "CERTIFIED"},
    ]}
    scope = issuer_quarantine(matrix=matrix, actions=actions, matrix_sha256="a" * 64)
    assert scope.admitted_action_ids == {action_ids[2]}
    assert scope.excluded_action_ids == set(action_ids[:2])
    assert scope.certified_action_ids == {action_ids[0], action_ids[2]}
    owners = {uuid.uuid4(): issuer_a, uuid.uuid4(): issuer_a, uuid.uuid4(): issuer_b}
    assert retained_instruments(owners, scope) == {
        instrument for instrument, issuer in owners.items() if issuer == issuer_b
    }


def test_unaccounted_original_action_cannot_be_silently_dropped() -> None:
    with pytest.raises(CertifiedScopeError, match="Every original action"):
        issuer_quarantine(
            matrix={"rows": []},
            actions=({"action_id": str(uuid.uuid4()), "issuer_id": str(uuid.uuid4())},),
            matrix_sha256="a" * 64,
        )


def test_coverage_never_shrinks_to_the_filtered_population_or_rewrites_membership() -> None:
    dates = pd.to_datetime(["2026-08-03", "2026-08-04"])
    index = pd.MultiIndex.from_tuples(
        [(dates[0], f"I{i}") for i in range(501)]
        + [(dates[1], f"I{i}") for i in range(504)],
        names=["datetime", "instrument"],
    )
    result = coverage_accounting(
        observations=492 + 495, expected_index=index, original_reference_count=503,
    )
    assert len(index) == 1005
    assert result["coverage_original_membership_slots"] == 1005
    assert result["coverage_applied_denominator"] == 503 + 504
    assert result["coverage"] == pytest.approx(987 / 1007)
    assert result["coverage"] < 1


def test_expected_coverage_slots_use_calendar_maturity_without_unknown_label_values() -> None:
    calendar = tuple(pd.bdate_range("2026-08-03", periods=5))
    membership = {session: {"IA", "IB", "QUARANTINED"} for session in calendar}
    expected = expected_test_index(
        membership=membership, calendar=calendar,
        start=calendar[0], end=calendar[-1], horizon_sessions=2,
    )
    assert len(expected) == 9
    assert "QUARANTINED" in expected.get_level_values("instrument")
    assert expected.get_level_values("datetime").max() == calendar[2]


def proof_fixture(tmp_path: Path) -> tuple[dict, dict, Path]:
    document = tmp_path / "original.htm"
    document.write_bytes(b"Original immutable SEC document")
    action = {
        "action_id": str(uuid.uuid4()), "issuer_id": str(uuid.uuid4()), "cik": "0000000001",
        "effective_date": "2026-06-01", "split_from": "1", "split_to": "2",
        "payload_hash": "b" * 64,
    }
    row = {
        "action_id": action["action_id"], "certified": True,
        "stored_execution_session": action["effective_date"], "stored_split_from": "1",
        "stored_split_to": "2", "stored_payload_hash": action["payload_hash"],
        "proof": {
            "publication_version_bound": "2026-06-02T20:00:00+00:00",
            "url": "https://www.sec.gov/Archives/edgar/data/1/000000000126000001/report.htm",
            "document_sha256": hashlib.sha256(document.read_bytes()).hexdigest(),
            "provider_historical_revision_claim": False,
        },
    }
    return row, action, document


def test_verified_fact_publication_is_distinct_from_actual_now_document_retrieval(
    tmp_path: Path,
) -> None:
    row, action, document = proof_fixture(tmp_path)
    accepted = datetime(2026, 6, 2, 20, tzinfo=UTC)
    assert verify_split_proof(
        row=row, action=action, cutoff_at=datetime(2026, 9, 26, tzinfo=UTC),
        document_path=document, accepted_at=accepted,
    ) == accepted


def test_old_folder_or_effective_date_cannot_replace_future_or_unproven_publication(
    tmp_path: Path,
) -> None:
    row, action, document = proof_fixture(tmp_path)
    with pytest.raises(CertifiedScopeError, match="publication"):
        verify_split_proof(
            row=row, action=action, cutoff_at=datetime(2026, 6, 1, tzinfo=UTC),
            document_path=document, accepted_at=datetime(2026, 6, 2, 20, tzinfo=UTC),
        )
    with pytest.raises(CertifiedScopeError, match="publication"):
        verify_split_proof(
            row=row, action=action, cutoff_at=datetime(2026, 9, 26, tzinfo=UTC),
            document_path=document, accepted_at=datetime(2026, 6, 1, tzinfo=UTC),
        )


def test_mismatched_ratio_or_document_is_not_certified(tmp_path: Path) -> None:
    row, action, document = proof_fixture(tmp_path)
    action["split_to"] = "3"
    with pytest.raises(CertifiedScopeError, match="facts differ"):
        verify_split_proof(
            row=row, action=action, cutoff_at=datetime(2026, 9, 26, tzinfo=UTC),
            document_path=document, accepted_at=datetime(2026, 6, 2, 20, tzinfo=UTC),
        )


@pytest.mark.parametrize("change", [
    {"data_publication_max": "2026-10-01T00:00:00+00:00"},
    {"generated_at": "2026-09-01T00:00:00+00:00"},
    {"knowledge_mode": "OPERATIONAL_REPLAY"},
])
def test_scope_cannot_backdate_generation_or_admit_future_data(
    tmp_path: Path, change: dict[str, object],
) -> None:
    payload = {
        "schema_version": SCOPE_VERSION, "knowledge_mode": "HISTORICAL_RECONSTRUCTION",
        "cutoff_at": "2026-09-26T09:30:00+00:00",
        "data_publication_max": "2026-09-25T20:15:00+00:00",
        "generated_at": "2026-10-18T03:00:00+00:00",
        "scope": {
            "original_reference_count": 503, "original_membership_preserved": True,
            "completeness": "CERTIFIED_ELIGIBLE_SCOPE_ONLY",
        },
        "artifacts": {},
    } | change
    path = tmp_path / "scope.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(CertifiedScopeError):
        read_scope_artifact(
            uri=path.as_uri(), expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            cutoff_at=datetime(2026, 9, 26, 9, 30, tzinfo=UTC),
        )
