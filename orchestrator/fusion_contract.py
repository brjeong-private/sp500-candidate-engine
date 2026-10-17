"""Versioned external candidate-list contract; no external analysis lifecycle."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from fractions import Fraction
from uuid import UUID

CONTRACT_VERSION = "fusion-top20-v1"
_ENVELOPE_KEYS = {
    "contract_version", "selection_type", "model_purpose", "status", "selection_run_id",
    "price_session_date", "cutoff_at", "execution_context_id", "quant_selection_run_id",
    "llm_preselection_run_id", "policy_version", "config_hash", "requested_count",
    "selected_count", "candidates", "payload_hash", "rrf_k",
}
_CANDIDATE_KEYS = {
    "instrument_id", "issuer_id", "ticker", "sector", "position", "quant_rank",
    "quant_rank_overall", "quant_predicted_return", "llm_rank", "llm_assessment_rank",
    "llm_score", "rrf_score", "rrf_numerator", "rrf_denominator", "selected_by_quant",
    "selected_by_llm", "quality_status", "risk_status", "reason_codes", "source_evidence_refs",
}


def canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def verify_envelope(
    payload: dict[str, object], *, run_id: str, analysis_date: str,
    policy_version: str, quant_id: str, llm_id: str,
    expected_config_hash: str,
) -> list[dict[str, object]]:
    k = payload.get("rrf_k")
    if (
        set(payload) != _ENVELOPE_KEYS
        or payload.get("contract_version") != CONTRACT_VERSION
        or payload.get("selection_type") != "FUSION"
        or payload.get("model_purpose") != "MEDIUM_20D"
        or payload.get("status") != "SUCCEEDED"
        or payload.get("selection_run_id") != run_id
        or payload.get("price_session_date") != analysis_date
        or payload.get("quant_selection_run_id") != quant_id
        or payload.get("llm_preselection_run_id") != llm_id
        or payload.get("policy_version") != policy_version
        or payload.get("config_hash") != expected_config_hash
        or type(payload.get("requested_count")) is not int
        or payload.get("requested_count") != 20
        or type(payload.get("selected_count")) is not int
        or payload.get("selected_count") != 20
        or type(k) is not int or k <= 0
        or payload.get("payload_hash") != canonical_hash({
            key: value for key, value in payload.items() if key != "payload_hash"
        })
    ):
        raise ValueError("Fusion envelope identity, policy or payload hash is invalid")
    for field in (
        "selection_run_id", "execution_context_id", "quant_selection_run_id",
        "llm_preselection_run_id",
    ):
        UUID(str(payload[field]))
    cutoff = datetime.fromisoformat(str(payload["cutoff_at"]).replace("Z", "+00:00"))
    if cutoff.tzinfo is None:
        raise ValueError("Fusion cutoff must be timezone aware")
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 20:
        raise ValueError("Fusion requires exactly 20 candidates")
    identities = []
    instruments, issuers = set(), set()
    order = []
    source_ranks = [set(), set()]
    for position, item in enumerate(candidates, 1):
        if not isinstance(item, dict) or set(item) != _CANDIDATE_KEYS:
            raise ValueError("Invalid Fusion candidate")
        instrument = str(UUID(str(item["instrument_id"])))
        issuer = str(UUID(str(item["issuer_id"])))
        if (
            type(item.get("position")) is not int or item["position"] != position
            or instrument in instruments or issuer in issuers
            or not isinstance(item.get("ticker"), str) or not item["ticker"]
            or item.get("quality_status") != "OK" or item.get("risk_status") != "PASSED"
        ):
            raise ValueError("Fusion candidate identity or eligibility is invalid")
        ranks = [item.get("quant_rank"), item.get("llm_rank")]
        if all(rank is None for rank in ranks) or any(
            rank is not None and (type(rank) is not int or not 1 <= rank <= 20)
            for rank in ranks
        ):
            raise ValueError("Invalid Fusion source rank")
        if (
            item.get("selected_by_quant") is not (ranks[0] is not None)
            or item.get("selected_by_llm") is not (ranks[1] is not None)
            or (ranks[0] is None) != (item.get("quant_predicted_return") is None)
            or (ranks[1] is None) != (item.get("llm_score") is None)
            or not isinstance(item.get("rrf_score"), (int, float))
            or not math.isfinite(item["rrf_score"])
        ):
            raise ValueError("Fusion candidate source flags or values are invalid")
        exact = Fraction(0)
        for index, rank in enumerate(ranks):
            if rank is not None:
                if rank in source_ranks[index]:
                    raise ValueError("Duplicate source rank")
                source_ranks[index].add(rank)
                exact += Fraction(1, k + rank)
        if (
            type(item["rrf_numerator"]) is not int
            or type(item["rrf_denominator"]) is not int
            or item["rrf_denominator"] <= 0
            or Fraction(item["rrf_numerator"], item["rrf_denominator"]) != exact
            or not math.isclose(float(exact), item["rrf_score"], rel_tol=0, abs_tol=1e-15)
        ):
            raise ValueError("Invalid Fusion exact score")
        for key in ("quant_predicted_return", "llm_score"):
            if item[key] is not None and (
                type(item[key]) not in {int, float} or not math.isfinite(item[key])
            ):
                raise ValueError("Invalid source score")
        if item["llm_score"] is not None and not 0 <= item["llm_score"] <= 100:
            raise ValueError("Invalid LLM score")
        references = item["source_evidence_refs"]
        if not isinstance(references, list) or len(references) > 10 \
                or (ranks[1] is not None and not references):
            raise ValueError("Invalid evidence references")
        for reference in references:
            UUID(str(reference))
        order.append((-exact, instrument))
        instruments.add(instrument)
        issuers.add(issuer)
        identities.append({
            "instrument_id": instrument, "issuer_id": issuer, "position": position,
        })
    if order != sorted(order):
        raise ValueError("Invalid Fusion deterministic order")
    return identities


def verify_ack(
    ack: dict[str, object], payload: dict[str, object],
    identities: list[dict[str, object]],
) -> None:
    if (
        ack.get("contract_version") != CONTRACT_VERSION
        or ack.get("selection_run_id") != payload["selection_run_id"]
        or ack.get("payload_hash") != payload["payload_hash"]
        or ack.get("status") not in {"ACCEPTED", "REUSED"}
        or type(ack.get("accepted_count")) is not int or ack["accepted_count"] != 20
        or ack.get("accepted_candidates") != identities
    ):
        raise ValueError("Fusion ACK must confirm the exact 20 identities and payload")
