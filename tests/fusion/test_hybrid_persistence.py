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
