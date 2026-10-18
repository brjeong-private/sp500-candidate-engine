from __future__ import annotations

import copy
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from fractions import Fraction
from pathlib import Path
from uuid import UUID

import pytest
from psycopg.types.json import Jsonb

from sp500_candidate_engine.analytics.config import load_versioned_config
from sp500_candidate_engine.database import _canonical_hash, _stable_uuid
from sp500_candidate_engine.fusion.policy import FusionInput, FusionPolicy, fuse_candidates
from sp500_candidate_engine.fusion.repository import FusionConflictError, FusionRepository
from sp500_candidate_engine.fusion.service import FusionService
from sp500_candidate_engine.llm_preselection.config import load_llm_preselection_config

NOW = datetime(2026, 10, 15, 9, 30, tzinfo=UTC)
DAY = date(2026, 10, 14)
ROOT = Path(__file__).resolve().parents[2]
CONTEXT, QUANT, LLM, UNIVERSE = (UUID(int=index) for index in range(1001, 1005))


class Cursor:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return copy.deepcopy(self.row)


class Connection:
    def __init__(self):
        self.tables = {}
        self.lock = threading.RLock()
        self.fail_table = None
        self.statements = []

    @contextmanager
    def transaction(self):
        with self.lock:
            before = copy.deepcopy(self.tables)
            try:
                yield self
            except BaseException:
                self.tables = before
                raise

    def execute(self, sql, params=()):
        assert sql.count("%s") == len(params), sql
        self.statements.append(sql)
        if "SELECT manifest_hash" in sql:
            return Cursor({"manifest_hash": "manifest-hash"})
        if "SELECT * FROM selection.fusion_run" in sql:
            return Cursor(next(
                (item for item in self.tables.get("selection.fusion_run", [])
                 if item["idempotency_key"] == params[0]), None
            ))
        insert = re.search(
            r"INSERT INTO ([\w.]+)\((.*?)\)\s*VALUES\s*\((.*?)\)\s*(?:RETURNING|$)",
            sql.strip(), re.S,
        )
        if insert is None:
            return Cursor(None)
        table = insert[1]
        if self.fail_table == table:
            raise RuntimeError("Injected write failure")
        columns = [value.strip() for value in insert[2].split(",")]
        expressions = [value.strip() for value in insert[3].split(",")]
        assert len(columns) == len(expressions)
        parameters = iter(params)
        values = []
        for expression in expressions:
            if expression == "%s":
                value = next(parameters)
                if isinstance(value, Jsonb):
                    value = value.obj
                    json.dumps(value)
            elif expression == "now()":
                value = NOW
            else:
                value = int(expression) if expression.isdigit() else expression.strip("'")
            values.append(value)
        row = dict(zip(columns, values, strict=True))
        if table == "selection.fusion_run":
            row.update(model_purpose="MEDIUM_20D", selection_type="FUSION",
                       requested_count=20, created_at=NOW)
        self.tables.setdefault(table, []).append(row)
        return Cursor(row if "RETURNING" in sql else None)


class Database:
    def __init__(self):
        self.connection = Connection()

    @contextmanager
    def connect(self, **kwargs):
        yield self.connection


def sources():
    candidates = tuple(
        FusionInput(UUID(int=index), UUID(int=index + 100), f"T{index}", f"S{index % 10}",
                    index, 0.1, index + 100)
        for index in range(1, 21)
    )
    return candidates, {item.instrument_id: () for item in candidates}


def persist(connection, result, *, key="same-key", payload_hash="same-hash"):
    return FusionRepository(connection).persist(
        context_id=CONTEXT, quant_id=QUANT, llm_id=LLM, target_session=DAY, cutoff_at=NOW,
        policy=FusionPolicy(), payload_hash=payload_hash, idempotency_key=key,
        provenance={"source_ids": [str(QUANT), str(LLM)]}, result=result,
        failure_code=None if result.status == "SUCCEEDED" else "UNION_SHORTFALL",
    )


def test_atomic_storage_and_concurrent_idempotency():
    connection = Connection()
    candidates, gates = sources()
    result = fuse_candidates(quantitative=candidates, llm=candidates, gate_reasons=gates)

    def execute():
        with connection.transaction():
            return persist(connection, result)

    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(lambda _: execute(), range(2)))
    assert len(connection.tables["selection.fusion_run"]) == 1
    assert len(connection.tables["selection.fusion_candidate"]) == 20
    assert len(connection.tables["selection.fusion_audit"]) == 20
    assert sum(item["reused"] for item in rows) == 1
    assert any("pg_advisory_xact_lock" in sql for sql in connection.statements)
    with pytest.raises(FusionConflictError), connection.transaction():
        persist(connection, result, payload_hash="changed-input")


def test_write_failure_rolls_back_run_candidates_and_audit():
    connection = Connection()
    connection.fail_table = "selection.fusion_audit"
    candidates, gates = sources()
    result = fuse_candidates(quantitative=candidates, llm=candidates, gate_reasons=gates)
    with pytest.raises(RuntimeError, match="Injected"), connection.transaction():
        persist(connection, result)
    assert connection.tables == {}


@pytest.mark.parametrize("corruption", ["score", "audit", "position"])
def test_corrupt_result_is_rejected_before_insert(corruption):
    connection = Connection()
    candidates, gates = sources()
    result = fuse_candidates(quantitative=candidates, llm=candidates, gate_reasons=gates)
    if corruption == "audit":
        result = replace(result, audit=result.audit[:19])
    else:
        first = replace(
            result.candidates[0],
            **({"rrf": Fraction(1)} if corruption == "score" else {"position": 2}),
        )
        result = replace(result, candidates=(first, *result.candidates[1:]))
    with pytest.raises(ValueError), connection.transaction():
        persist(connection, result)
    assert not connection.tables


def service_fixture(monkeypatch):
    database = Database()
    config = load_llm_preselection_config(
        ROOT / "config" / "llm_preselection" / "policy_event_v2.yaml"
    )
    quant_config = load_versioned_config(
        ROOT / "config" / "analytics" / "selection_medium_20d_v1.yaml"
    )
    items, gates = sources()
    candidate_rows = [
        {"instrument_id": item.instrument_id, "issuer_id": item.issuer_id, "symbol": item.symbol,
         "sector": item.sector, "position": item.position, "score": item.score,
         "original_rank": item.original_rank, "supported_count": 3, "weight_denominator": 70,
         "evidence_ids": [str(UUID(int=item.position + 10000))]}
        for item in items
    ]
    common = {
        "status": "SUCCEEDED", "requested_count": 20, "selected_count": 20,
        "execution_context_id": CONTEXT, "price_session_date": DAY, "cutoff_at": NOW,
        "candidates": candidate_rows,
    }
    quant = {
        **common, "selection_run_id": QUANT, "scoring_run_id": UUID(int=1010),
        "universe_version_id": UNIVERSE, "policy_version": quant_config.version,
        "policy_hash": quant_config.config_hash, "model_purpose": "MEDIUM_20D",
        "score_semantics": "PREDICTED_20D_RETURN", "label_semantics": "RAW_STOCK_20D_RETURN",
        "return_policy": "PRICE_RETURN",
        "scoring_status": "SUCCEEDED", "artifact_hash": "artifact",
        "export_context_id": CONTEXT, "export_status": "SUCCEEDED", "scores_match": True,
        "scoring_config_hash": "model-hash", "model_config_hash": "model-hash",
        "model_version_id": UUID(int=1011), "processor_version_id": None,
        "training_feature_run_id": UUID(int=1012), "export_run_id": UUID(int=1013),
    }
    llm = {
        **common, "run_id": LLM, "llm_ranking_run_id": UUID(int=1014),
        "policy_version": config.policy_version, "policy_hash": config.versioned.config_hash,
        "ranking_status": "SUCCEEDED", "universe_versions": [str(UNIVERSE)],
        "input_hash": "llm-input", "prompt_version": config.prompt_version,
        "deployment": "test", "api_version": "test", "evidence_schema_version": "2",
    }
    llm["candidates"] = copy.deepcopy(candidate_rows)
    for row in quant["candidates"]:
        row["reason_codes"] = ["MODEL_TOP_RANK"]
    for row in llm["candidates"]:
        event_id = str(UUID(int=row["position"] + 20000))
        snapshot_id = UUID(int=row["position"] + 30000)
        evidence_id = str(_stable_uuid("llm-run-evidence-link", (
            f"{llm['llm_ranking_run_id']}:{row['instrument_id']}:NEWS:{event_id}:{snapshot_id}"
        )))
        row["evidence_ids"] = [evidence_id]
        row.update(
            score=80.0,
            sub_scores={"earnings": 80, "business": 80, "event": 80,
                        "financial": None, "industry": None},
            missing_reasons={"financial": "No supplied facts", "industry": "No industry evidence"},
            rationale="Unverified free-form summary.",
            criterion_evidence=[
                {"evidence_link_id": evidence_id, "criterion": criterion,
                 "reason": f"Provided operating update supports {criterion} evaluation"}
                for criterion in ("earnings", "business", "event")
            ],
            packet={
                "schema_version": "2",
                "execution_context_id": str(CONTEXT), "target_session": DAY.isoformat(),
                "cutoff_at": NOW.isoformat(),
                "identity": {"instrument_id": str(row["instrument_id"]),
                             "issuer_id": str(row["issuer_id"])},
                "news": [{
                    "event_revision_id": event_id, "title": "Actual provided operating update",
                    "published_at": (NOW - timedelta(hours=1)).isoformat(),
                }],
            },
            evidence_links=[{
                "evidence_link_id": evidence_id, "instrument_id": str(row["instrument_id"]),
                "source_snapshot_id": str(snapshot_id),
                "source_kind": "NEWS", "entity_key": event_id, "manifest_member": True,
                "source_available_at": (NOW - timedelta(hours=1)).isoformat(),
                "observed_at": (NOW - timedelta(minutes=30)).isoformat(),
                "revision_no": 1,
                "revision_observed_at": (NOW - timedelta(minutes=30)).isoformat(),
            }],
        )
        row["packet_hash"] = _canonical_hash(row["packet"])
    context = {
        "execution_context_id": CONTEXT, "input_manifest_id": UUID(int=1005),
        "cutoff_at": NOW, "knowledge_mode": "OPERATIONAL_REPLAY",
    }
    monkeypatch.setattr(
        "sp500_candidate_engine.fusion.service.SourceRepository.read_context",
        lambda *args, **kwargs: context,
    )
    monkeypatch.setattr(
        FusionRepository, "read_sources", lambda *args: (quant, llm)
    )
    monkeypatch.setattr(
        "sp500_candidate_engine.fusion.service.read_selection_eligibility",
        lambda *args, **kwargs: ([
            {**item, "universe_version_id": UNIVERSE} for item in candidate_rows
        ], gates),
    )
    service = FusionService(
        database, FusionPolicy(), config, quant_config.version, quant_config.config_hash
    )
    return database, service, quant, llm


def test_service_pins_sources_and_persists_reproducible_lineage(monkeypatch):
    database, service, quant, llm = service_fixture(monkeypatch)
    first = service.run(context_id=CONTEXT, target_session=DAY, quant_id=QUANT, llm_id=LLM)
    second = service.run(context_id=CONTEXT, target_session=DAY, quant_id=QUANT, llm_id=LLM)
    assert first.status == "SUCCEEDED"
    assert first.fusion_run_id == second.fusion_run_id and second.reused
    run = database.connection.tables["selection.fusion_run"][0]
    assert run["provenance"]["manifest_hash"] == "manifest-hash"
    assert run["provenance"]["quant_lineage"]["scoring_run_id"] == str(quant["scoring_run_id"])
    assert run["provenance"]["llm_lineage"]["llm_ranking_run_id"] == str(llm["llm_ranking_run_id"])
    assert run["provenance"]["eligibility_audit_hash"]


def test_changed_hard_gate_decision_conflicts_with_same_explicit_key(monkeypatch):
    database, service, quant, llm = service_fixture(monkeypatch)
    first = service.run(
        context_id=CONTEXT, target_session=DAY, quant_id=QUANT, llm_id=LLM,
        idempotency_key="fixed-gate-key",
    )
    assert first.status == "SUCCEEDED"
    candidates, gates = sources()
    gates[candidates[0].instrument_id] = ("BLOCKING_QUALITY_ISSUE",)
    monkeypatch.setattr(
        "sp500_candidate_engine.fusion.service.read_selection_eligibility",
        lambda *args, **kwargs: ([
            {
                "instrument_id": item.instrument_id, "issuer_id": item.issuer_id,
                "symbol": item.symbol, "sector": item.sector, "universe_version_id": UNIVERSE,
            } for item in candidates
        ], gates),
    )
    with pytest.raises(FusionConflictError):
        service.run(
            context_id=CONTEXT, target_session=DAY, quant_id=QUANT, llm_id=LLM,
            idempotency_key="fixed-gate-key",
        )
    assert len(database.connection.tables["selection.fusion_run"]) == 1


@pytest.mark.parametrize("source,field,value", [
    ("llm", "execution_context_id", UUID(int=99999)),
    ("llm", "cutoff_at", NOW + timedelta(seconds=1)),
    ("llm", "policy_version", "legacy-policy"),
    ("llm", "policy_hash", "wrong"),
    ("llm", "status", "SHORTFALL"),
    ("llm", "universe_versions", ["wrong-universe"]),
    ("quant", "model_purpose", "SHORT_5D"),
    ("quant", "score_semantics", "PREDICTED_5D_RETURN"),
    ("quant", "scores_match", False),
    ("quant", "export_context_id", UUID(int=99999)),
])
def test_source_mismatch_is_persisted_failed_not_fallback(monkeypatch, source, field, value):
    database, service, quant, llm = service_fixture(monkeypatch)
    (quant if source == "quant" else llm)[field] = value
    result = service.run(context_id=CONTEXT, target_session=DAY, quant_id=QUANT, llm_id=LLM)
    assert result.status == "FAILED"
    assert result.selected_count == 0
    assert database.connection.tables.get("selection.fusion_candidate", []) == []
    assert database.connection.tables["selection.fusion_run"][0]["failure_code"]


def stored_read_row(database):
    from backend.app.schemas.fusions import FusionRun

    run = database.connection.tables["selection.fusion_run"][-1]
    row = {key: value for key, value in run.items() if key in FusionRun.model_fields}
    row["candidates"] = [
        copy.deepcopy(item["candidate"])
        for item in database.connection.tables.get("selection.fusion_candidate", [])
        if item["fusion_run_id"] == run["fusion_run_id"]
    ]
    return row


def test_explanation_preserves_scores_scored_pairs_and_deterministic_identity(monkeypatch):
    from backend.app.repositories.fusions import FusionReadRepository
    from sp500_candidate_engine.fusion.explanations import explanation_output_hash

    database, service, quant, llm = service_fixture(monkeypatch)
    result = service.run(context_id=CONTEXT, target_session=DAY, quant_id=QUANT, llm_id=LLM)
    row = stored_read_row(database)
    monkeypatch.setattr(FusionReadRepository, "fetch", lambda *args: [copy.deepcopy(row)])
    repository = FusionReadRepository(database)
    explanations = repository.explanations(result.fusion_run_id)
    assert explanations.status == "RECORDED"
    assert len(explanations.candidates) == 20
    snapshot = explanations.candidates[0].explanation
    assert snapshot.quant.score == quant["candidates"][0]["score"]
    assert snapshot.quant.reason_codes == ("MODEL_TOP_RANK",)
    assert snapshot.llm.score == 80
    assert snapshot.llm.sub_scores["financial"] is None
    assert snapshot.llm.supported_count == 3 and snapshot.llm.weight_denominator == 70
    assert len(snapshot.llm.evidence) == 3
    assert len({item.evidence_link_id for item in snapshot.llm.evidence}) == 1
    assert {item.criterion for item in snapshot.llm.evidence} == {"earnings", "business", "event"}
    assert snapshot.llm.summary_method == "DETERMINISTIC_CITATIONS"
    assert "Unverified" not in snapshot.llm.summary
    assert all(item.metadata_status == "PARTIAL" and item.source_url is None
               for item in snapshot.llm.evidence)
    assert row["provenance"]["explanation_output_hash"] == explanation_output_hash({
        str(item["instrument_id"]): item["explanation"] for item in row["candidates"]
    })
    with_explanation = repository.handoff(result.fusion_run_id)
    for item in row["candidates"]:
        item.pop("explanation")
        item["unrelated_future_field"] = "must not enter v1"
    without_explanation = repository.handoff(result.fusion_run_id)
    assert with_explanation == without_explanation
    assert not any("explanation" in item or "unrelated_future_field" in item
                   for item in with_explanation["candidates"])


@pytest.mark.parametrize("corruption", [
    "future_source", "future_published", "instrument", "snapshot", "manifest",
    "trimmed", "packet_hash", "criterion", "score", "denominator", "duplicate",
    "backdated_correction",
])
def test_invalid_explanation_fails_closed_without_losing_upstream(monkeypatch, corruption):
    database, service, quant, llm = service_fixture(monkeypatch)
    before_quant = copy.deepcopy(quant)
    candidate = llm["candidates"][0]
    link = candidate["evidence_links"][0]
    if corruption == "future_source":
        link["source_available_at"] = (NOW + timedelta(microseconds=1)).isoformat()
    elif corruption == "backdated_correction":
        link.update(revision_no=2, revision_observed_at=(NOW + timedelta(days=1)).isoformat())
    elif corruption == "future_published":
        candidate["packet"]["news"][0]["published_at"] = (
            NOW + timedelta(microseconds=1)
        ).isoformat()
        candidate["packet_hash"] = _canonical_hash(candidate["packet"])
    elif corruption == "instrument":
        link["instrument_id"] = str(UUID(int=999))
    elif corruption == "snapshot":
        link["source_snapshot_id"] = str(UUID(int=999))
    elif corruption == "manifest":
        link["manifest_member"] = False
    elif corruption == "trimmed":
        candidate["packet"]["news"] = []
        candidate["packet_hash"] = _canonical_hash(candidate["packet"])
    elif corruption == "packet_hash":
        candidate["packet_hash"] = "invalid"
    elif corruption == "criterion":
        candidate["criterion_evidence"][0]["criterion"] = "financial"
    elif corruption == "score":
        candidate["sub_scores"]["earnings"] = 81
    elif corruption == "denominator":
        candidate["weight_denominator"] = 71
    else:
        candidate["criterion_evidence"].append(copy.deepcopy(candidate["criterion_evidence"][0]))
    result = service.run(context_id=CONTEXT, target_session=DAY, quant_id=QUANT, llm_id=LLM)
    assert result.status == "FAILED" and result.selected_count == 0
    assert result.failure_code == "FUSION_EXPLANATION_VALIDATION_FAILED"
    assert not database.connection.tables.get("selection.fusion_candidate")
    assert quant == before_quant


def test_explanation_routes_legacy_snapshots_and_integrity_errors(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.app.repositories.fusions import FusionReadRepository
    from backend.app.routers.fusions import explanations_router

    database, service, _, _ = service_fixture(monkeypatch)
    result = service.run(context_id=CONTEXT, target_session=DAY, quant_id=QUANT, llm_id=LLM)
    row = stored_read_row(database)
    monkeypatch.setattr(FusionReadRepository, "fetch", lambda *args: [copy.deepcopy(row)])
    app = FastAPI()
    app.state.database = database
    app.include_router(explanations_router)
    with TestClient(app) as client:
        url = f"/api/v2/fusion-selections/{result.fusion_run_id}/explanations"
        response = client.get(url)
        assert response.status_code == 200
        assert response.json()["status"] == "RECORDED"
        assert response.json()["cutoff_at"].startswith("2026-10-15T09:30:00")
        saved = copy.deepcopy(row)
        row["candidates"][0]["explanation"]["quant"]["score"] += 1
        assert client.get(url).status_code == 500
        row = copy.deepcopy(saved)
        row["candidates"][0].pop("explanation")
        assert client.get(url).status_code == 500
        row = copy.deepcopy(saved)
        row["provenance"] = {"manifest_hash": "historical"}
        for item in row["candidates"]:
            item.pop("explanation")
        legacy = copy.deepcopy(row)
        old = client.get(url)
        assert old.status_code == 200 and old.json()["status"] == "NOT_RECORDED"
        assert all(item["status"] == "NOT_RECORDED" and item["explanation"] is None
                   for item in old.json()["candidates"])
        assert row == legacy
        monkeypatch.setattr(FusionReadRepository, "fetch", lambda *args: [])
        assert client.get(url).status_code == 404


@pytest.mark.parametrize(("source_date", "precision", "verification_method", "expected_status"), [
    (DAY, "DAY", "PERIOD_SEARCH_SOURCE_DATES", 200),
    (NOW.date(), "TIMESTAMP", "PERIOD_SEARCH_SOURCE_DATES", 200),
    (NOW.date(), "DAY", "PERIOD_SEARCH_SOURCE_DATES", 500),
    (NOW.date() + timedelta(days=1), "DAY", "PERIOD_SEARCH_SOURCE_DATES", 500),
    (DAY, "DAY", "UNVERIFIED_SEARCH", 500),
])
def test_period_search_explanation_api_preserves_witness_and_rejects_invalid_dates(
    monkeypatch, source_date, precision, verification_method, expected_status,
):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.app.repositories.fusions import FusionReadRepository
    from backend.app.routers.fusions import explanations_router, router
    from sp500_candidate_engine.fusion.explanations import (
        EXTERNAL_SCHEMA_VERSION,
        explanation_output_hash,
    )

    database, service, _, _ = service_fixture(monkeypatch)
    result = service.run(context_id=CONTEXT, target_session=DAY, quant_id=QUANT, llm_id=LLM)
    row = stored_read_row(database)
    for candidate in row["candidates"]:
        candidate["explanation"]["schema_version"] = EXTERNAL_SCHEMA_VERSION
    evidence = row["candidates"][0]["explanation"]["llm"]["evidence"][0]
    evidence["source_url"] = "https://news.example.test/company-update"
    evidence["external_source"] = {
        "source_layer": "LLM_SEARCH_VERIFIED",
        "source_url": evidence["source_url"],
        "tool_response_hash": "a" * 64,
        "evidence_hash": "b" * 64,
        "artifact_key": "c" * 64 + ".json",
        "parent_accepted_at": (NOW - timedelta(days=2)).isoformat(),
        "source_available_at": NOW.isoformat(),
        "source_local_date": source_date.isoformat(),
        "source_date_precision": precision,
        "retrieved_at": (NOW + timedelta(days=1)).isoformat(),
        "model_snapshot": None,
        "verification_method": verification_method,
    }
    provenance = row["provenance"]
    provenance["explanation_schema_version"] = EXTERNAL_SCHEMA_VERSION
    provenance["explanation_config"]["schema_version"] = EXTERNAL_SCHEMA_VERSION
    provenance["explanation_config_hash"] = _canonical_hash(provenance["explanation_config"])
    provenance["explanation_output_hash"] = explanation_output_hash({
        str(candidate["instrument_id"]): candidate["explanation"]
        for candidate in row["candidates"]
    })
    monkeypatch.setattr(FusionReadRepository, "fetch", lambda *args: [copy.deepcopy(row)])
    app = FastAPI()
    app.state.database = database
    app.include_router(router)
    app.include_router(explanations_router)
    with TestClient(app) as client:
        response = client.get(
            f"/api/v2/fusion-selections/{result.fusion_run_id}/explanations"
        )
        assert response.status_code == expected_status
        if expected_status == 200:
            payload = response.json()
            assert payload["status"] == "RECORDED"
            assert payload["schema_version"] == EXTERNAL_SCHEMA_VERSION
            assert len(payload["candidates"]) == 20
            returned = payload["candidates"][0]["explanation"]["llm"]["evidence"][0]
            assert returned["summary"] == evidence["summary"]
            assert returned["source_url"] == evidence["source_url"]
            witness = returned["external_source"]
            for field in (
                "source_layer", "source_url", "tool_response_hash", "evidence_hash",
                "artifact_key", "source_local_date", "source_date_precision",
                "verification_method", "parent_accepted_at", "model_snapshot",
            ):
                assert witness[field] == evidence["external_source"][field]
            for field in ("source_available_at", "retrieved_at"):
                assert datetime.fromisoformat(witness[field]) == datetime.fromisoformat(
                    evidence["external_source"][field]
                )
            assert payload["candidates"][0]["explanation"]["quant"]["score"] == 0.1
            assert payload["candidates"][0]["explanation"]["fusion"]["rrf_k"] == 10
        legacy = client.get(f"/api/v1/fusion-selections/{result.fusion_run_id}")
        assert legacy.status_code == 200
        assert len(legacy.json()["candidates"]) == 20
        assert all("explanation" not in item for item in legacy.json()["candidates"])


def test_null_criterion_citations_remain_unscored_and_partial_metadata_is_explicit(monkeypatch):
    database, service, _, llm = service_fixture(monkeypatch)
    candidate = llm["candidates"][0]
    candidate["criterion_evidence"].append({
        "evidence_link_id": candidate["evidence_ids"][0], "criterion": "financial",
        "reason": "The supplied news has no financial figures",
    })
    candidate["packet"]["news"][0].pop("title")
    candidate["packet"]["news"][0]["source_url"] = "http://unsafe.example.test"
    candidate["packet_hash"] = _canonical_hash(candidate["packet"])
    result = service.run(context_id=CONTEXT, target_session=DAY, quant_id=QUANT, llm_id=LLM)
    assert result.status == "SUCCEEDED"
    snapshot = stored_read_row(database)["candidates"][0]["explanation"]
    assert snapshot["llm"]["score"] == 80 and snapshot["llm"]["supported_count"] == 3
    assert len(snapshot["llm"]["evidence"]) == 3
    assert all(item["source_label"] is None and item["source_url"] is None
               and item["metadata_status"] == "PARTIAL"
               for item in snapshot["llm"]["evidence"])
    assert "no financial figures" not in snapshot["llm"]["summary"]


def test_explanation_contract_changes_do_not_reuse_old_run(monkeypatch):
    database, service, _, llm = service_fixture(monkeypatch)
    first = service.run(context_id=CONTEXT, target_session=DAY, quant_id=QUANT, llm_id=LLM)
    llm["candidates"][0]["rationale"] = "Different unverified rationale"
    second = service.run(context_id=CONTEXT, target_session=DAY, quant_id=QUANT, llm_id=LLM)
    assert second.status == "SUCCEEDED" and second.fusion_run_id != first.fusion_run_id
    assert not second.reused


def test_explanation_single_source_never_copies_other_share_class(monkeypatch):
    database, service, _, llm = service_fixture(monkeypatch)
    candidate = llm["candidates"][0]
    candidate["instrument_id"] = UUID(int=9999)
    candidate["packet"]["identity"]["instrument_id"] = str(candidate["instrument_id"])
    candidate["packet_hash"] = _canonical_hash(candidate["packet"])
    link = candidate["evidence_links"][0]
    link["instrument_id"] = str(candidate["instrument_id"])
    evidence_id = str(_stable_uuid("llm-run-evidence-link", (
        f"{llm['llm_ranking_run_id']}:{candidate['instrument_id']}:NEWS:"
        f"{link['entity_key']}:{link['source_snapshot_id']}"
    )))
    link["evidence_link_id"] = evidence_id
    candidate["evidence_ids"] = [evidence_id]
    for citation in candidate["criterion_evidence"]:
        citation["evidence_link_id"] = evidence_id
    from sp500_candidate_engine.fusion import service as service_module

    members, gates = service_module.read_selection_eligibility(None)
    members.append({**candidate, "universe_version_id": UNIVERSE})
    gates[candidate["instrument_id"]] = ()
    monkeypatch.setattr(
        "sp500_candidate_engine.fusion.service.read_selection_eligibility",
        lambda *args, **kwargs: (members, gates),
    )
    result = service.run(context_id=CONTEXT, target_session=DAY, quant_id=QUANT, llm_id=LLM)
    assert result.status == "SUCCEEDED"
    first = next(item for item in stored_read_row(database)["candidates"]
                 if item["issuer_id"] == str(UUID(int=101)))
    snapshot = first["explanation"]
    assert first["instrument_id"] == str(UUID(int=1))
    assert snapshot["llm"]["selected_in_source"] is False
    assert snapshot["llm"]["score"] is None and snapshot["llm"]["evidence"] == []
    assert snapshot["fusion"]["llm_contribution"] is None


def test_explanation_bounds_source_labels_safe_urls_and_summary(monkeypatch):
    database, service, _, llm = service_fixture(monkeypatch)
    candidate = llm["candidates"][0]
    candidate["packet"]["news"][0].update(
        title="Actual title " * 100, source_url="https://news.example.test/article/123",
    )
    for citation in candidate["criterion_evidence"]:
        citation["reason"] = "Specific reported operating change. " * 15
    candidate["packet_hash"] = _canonical_hash(candidate["packet"])
    result = service.run(context_id=CONTEXT, target_session=DAY, quant_id=QUANT, llm_id=LLM)
    assert result.status == "SUCCEEDED"
    snapshot = stored_read_row(database)["candidates"][0]["explanation"]
    assert len(snapshot["llm"]["summary"]) == 600
    assert all(
        len(item["source_label"]) == 256 and len(item["summary"]) <= 600
        and item["metadata_status"] == "AVAILABLE"
        and item["source_url"] == "https://news.example.test/article/123"
        for item in snapshot["llm"]["evidence"]
    )


def test_explanation_contract_is_part_of_fusion_input_identity(monkeypatch):
    from sp500_candidate_engine.fusion.repository import source_payload_hash

    _, service, quant, llm = service_fixture(monkeypatch)
    original = source_payload_hash(quant, llm, {}, service.policy)
    current = source_payload_hash(
        quant, llm, {"explanation_schema_version": "candidate-explanation-v1"}, service.policy,
    )
    newer = source_payload_hash(
        quant, llm, {"explanation_schema_version": "candidate-explanation-v2"}, service.policy,
    )
    assert len({original, current, newer}) == 3


def test_explanation_hash_survives_jsonb_numeric_normalization_without_changing_v1_hash():
    from sp500_candidate_engine.fusion.explanations import explanation_output_hash

    fractional = {"candidate": {"llm": {"score": 80.0, "sub_scores": {"earnings": 75.0}}}}
    integral = {"candidate": {"llm": {"score": 80, "sub_scores": {"earnings": 75}}}}
    assert explanation_output_hash(fractional) == explanation_output_hash(integral)
    assert _canonical_hash(fractional) != _canonical_hash(integral)
