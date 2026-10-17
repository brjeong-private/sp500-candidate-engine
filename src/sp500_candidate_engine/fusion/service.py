from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sp500_candidate_engine.analytics.source_repository import SourceRepository
from sp500_candidate_engine.database import Database, _canonical_hash
from sp500_candidate_engine.fusion.policy import FusionInput, FusionPolicy, fuse_candidates
from sp500_candidate_engine.fusion.repository import FusionRepository, source_payload_hash
from sp500_candidate_engine.llm_preselection.config import LlmPreselectionConfig
from sp500_candidate_engine.selection.eligibility import read_selection_eligibility

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FusionSummary:
    fusion_run_id: uuid.UUID
    status: str
    selected_count: int
    failure_code: str | None
    reused: bool


def _inputs(row: dict[str, object]) -> tuple[FusionInput, ...]:
    candidates = row["candidates"]
    if not isinstance(candidates, list):
        raise ValueError("Source candidates are not a list")
    result = []
    for item in candidates:
        if not isinstance(item, dict):
            raise ValueError("Invalid source candidate object")
        if type(item["position"]) is not int or type(item["original_rank"]) is not int \
                or not isinstance(item["score"], (float, int, Decimal)):
            raise ValueError("Invalid source numeric values")
        result.append(FusionInput(
            uuid.UUID(str(item["instrument_id"])), uuid.UUID(str(item["issuer_id"])),
            str(item["symbol"]), str(item["sector"]) if item["sector"] is not None else None,
            item["position"], float(item["score"]), item["original_rank"],
            tuple(str(value) for value in item.get("evidence_ids", ())),
        ))
    return tuple(result)


class FusionService:
    def __init__(
        self, database: Database, policy: FusionPolicy, llm_config: LlmPreselectionConfig,
        quantitative_policy_version: str, quantitative_policy_hash: str,
    ) -> None:
        self.database = database
        self.policy = policy
        self.llm_config = llm_config
        self.quantitative_policy_version = quantitative_policy_version
        self.quantitative_policy_hash = quantitative_policy_hash

    def run(
        self, *, context_id: uuid.UUID, target_session: date,
        quant_id: uuid.UUID | None, llm_id: uuid.UUID | None,
        idempotency_key: str | None = None,
    ) -> FusionSummary:
        with self.database.connect() as connection, connection.transaction():
            source = SourceRepository(connection)
            context = source.read_context(execution_context_id=context_id)
            cutoff = context["cutoff_at"]
            if not isinstance(cutoff, datetime):
                raise TypeError("Context cutoff must be a datetime")
            manifest = connection.execute(
                "SELECT manifest_hash FROM ops.input_manifest WHERE input_manifest_id = %s",
                (context["input_manifest_id"],),
            ).fetchone()
            if manifest is None:
                raise ValueError("Missing Fusion manifest")
            repository = FusionRepository(connection)
            quant, llm = repository.read_sources(quant_id, llm_id)
            provenance: dict[str, object] = {
                "context": {key: str(value) for key, value in context.items()},
                "manifest_hash": manifest["manifest_hash"],
                "target_session": target_session.isoformat(),
                "quant_selection_run_id": str(quant_id) if quant_id else None,
                "llm_preselection_run_id": str(llm_id) if llm_id else None,
                "expected_llm_policy_hash": self.llm_config.versioned.config_hash,
                "expected_quant_policy_version": self.quantitative_policy_version,
                "expected_quant_policy_hash": self.quantitative_policy_hash,
            }
            result = None
            failure_code = None
            try:
                if quant is None or llm is None:
                    raise ValueError("UPSTREAM_RUN_MISSING")
                if (
                    not self.llm_config.event_policy
                    or llm["policy_version"] != self.llm_config.policy_version
                    or llm["policy_hash"] != self.llm_config.versioned.config_hash
                    or quant["policy_version"] != self.quantitative_policy_version
                    or quant["policy_hash"] != self.quantitative_policy_hash
                    or quant["model_purpose"] != "MEDIUM_20D"
                    or quant["score_semantics"] != "PREDICTED_20D_RETURN"
                    or quant["label_semantics"] != "RAW_STOCK_20D_RETURN"
                    or quant["return_policy"] != "PRICE_RETURN"
                ):
                    raise ValueError("SOURCE_POLICY_MISMATCH")
                for run in (quant, llm):
                    if (
                        run["status"] != "SUCCEEDED" or run["requested_count"] != 20
                        or run["selected_count"] != 20
                        or run["execution_context_id"] != context_id
                        or run["price_session_date"] != target_session
                        or run["cutoff_at"] != cutoff
                    ):
                        raise ValueError("SOURCE_CONTEXT_OR_STATUS_MISMATCH")
                if quant["scoring_status"] != "SUCCEEDED" or llm["ranking_status"] != "SUCCEEDED":
                    raise ValueError("UPSTREAM_RANKING_FAILED")
                if (
                    not quant["artifact_hash"] or quant["export_context_id"] != context_id
                    or quant["export_status"] != "SUCCEEDED" or not quant["scores_match"]
                    or quant["scoring_config_hash"] != quant["model_config_hash"]
                ):
                    raise ValueError("QUANT_ARTIFACT_OR_SCORE_MISMATCH")
                if llm["universe_versions"] != [str(quant["universe_version_id"])]:
                    raise ValueError("SOURCE_UNIVERSE_MISMATCH")
                members, gates = read_selection_eligibility(
                    source, execution_context_id=context_id, target_session=target_session
                )
                if not members or {str(member["universe_version_id"]) for member in members} != {
                    str(quant["universe_version_id"])
                }:
                    raise ValueError("MANIFEST_UNIVERSE_MISMATCH")
                quant_inputs, llm_inputs = _inputs(quant), _inputs(llm)
                assessed_candidates = llm["candidates"]
                if not isinstance(assessed_candidates, list):
                    raise ValueError("LLM candidates must be a list")
                if any(
                    type(item.get("supported_count")) is not int or item["supported_count"] < 3
                    or type(item.get("weight_denominator")) is not int
                    or not 1 <= item["weight_denominator"] <= 100
                    for item in assessed_candidates
                ):
                    raise ValueError("LLM_CRITERION_COVERAGE_MISMATCH")
                identities = {uuid.UUID(str(member["instrument_id"])): member for member in members}
                for item in (*quant_inputs, *llm_inputs):
                    member = identities.get(item.instrument_id)
                    if member is not None and (
                        str(member["issuer_id"]) != str(item.issuer_id)
                        or member["symbol"] != item.symbol or member["sector"] != item.sector
                    ):
                        raise ValueError("SOURCE_INSTRUMENT_MISMATCH")
                result = fuse_candidates(
                    quantitative=quant_inputs, llm=llm_inputs,
                    gate_reasons=gates, policy=self.policy,
                )
                if result.status == "SHORTFALL":
                    failure_code = "INSUFFICIENT_UNION_CANDIDATES"
            except (ValueError, KeyError, TypeError, OverflowError) as error:
                logger.exception("fusion_input_validation_failed")
                failure_code = "FUSION_INPUT_VALIDATION_FAILED"
                provenance["validation_error_type"] = type(error).__name__
                provenance["validation_error_code"] = (
                    str(error) if isinstance(error, ValueError) else "INVALID_SOURCE_SHAPE"
                )
            provenance["quant_source_hash"] = _canonical_hash(quant)
            provenance["llm_source_hash"] = _canonical_hash(llm)
            if result is not None:
                provenance["eligibility_audit_hash"] = _canonical_hash(result.audit)
            for name, run, fields in (
                ("quant_lineage", quant, (
                    "scoring_run_id", "model_version_id", "artifact_hash",
                    "processor_version_id", "training_feature_run_id", "export_run_id",
                    "scoring_config_hash", "policy_version", "policy_hash", "universe_version_id",
                    "score_semantics", "label_semantics", "return_policy",
                )),
                ("llm_lineage", llm, (
                    "llm_ranking_run_id", "policy_version", "policy_hash", "input_hash",
                    "prompt_version", "deployment", "api_version", "evidence_schema_version",
                )),
            ):
                provenance[name] = {
                    field: str(run[field]) if isinstance(run.get(field), uuid.UUID)
                    else run.get(field)
                    for field in fields
                } if run is not None else None
            payload_hash = source_payload_hash(quant, llm, provenance, self.policy)
            key = idempotency_key or "fusion-" + payload_hash
            row = repository.persist(
                context_id=context_id, quant_id=quant_id if quant is not None else None,
                llm_id=llm_id if llm is not None else None,
                target_session=target_session, cutoff_at=cutoff, policy=self.policy,
                payload_hash=payload_hash, idempotency_key=key,
                provenance=provenance, result=result, failure_code=failure_code,
            )
            selected_count, failure = row["selected_count"], row["failure_code"]
            if type(selected_count) is not int or not (
                failure is None or isinstance(failure, str)
            ):
                raise TypeError("Stored Fusion result has invalid count or failure code")
            return FusionSummary(
                uuid.UUID(str(row["fusion_run_id"])), str(row["status"]),
                selected_count, failure, bool(row["reused"]),
            )
