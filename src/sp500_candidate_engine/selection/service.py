from __future__ import annotations

import uuid
from datetime import date, datetime

from sp500_candidate_engine.selection.policy import SelectionResult


def candidate_result_payload(
    *,
    selection_run_id: uuid.UUID,
    scoring_run_id: uuid.UUID,
    model_version_id: uuid.UUID,
    execution_context_id: uuid.UUID,
    price_session_date: date,
    cutoff_at: datetime,
    generated_at: datetime,
    policy_version: str,
    result: SelectionResult,
    model_status: str = "SHADOW",
    promotion_gate_passed: bool = False,
) -> dict[str, object]:
    return {
        "selection_run_id": str(selection_run_id),
        "selection_type": "QUANTITATIVE",
        "price_session_date": price_session_date.isoformat(),
        "cutoff_at": cutoff_at.isoformat(),
        "generated_at": generated_at.isoformat(),
        "execution_context_id": str(execution_context_id),
        "scoring_run_id": str(scoring_run_id),
        "model_version_id": str(model_version_id),
        "policy_version": policy_version,
        "model_status": model_status,
        "promotion_gate_passed": promotion_gate_passed,
        "status": result.status,
        "soft_constraints_relaxed": list(result.soft_constraints_relaxed),
        "candidates": [
            {
                "position": candidate.position,
                "instrument_id": str(candidate.instrument_id),
                "symbol": candidate.symbol,
                "sector": candidate.sector,
                "score": candidate.score,
                "rank_overall": candidate.rank_overall,
                "score_percentile": candidate.score_percentile,
                "rank_sector": candidate.rank_sector,
                "quality_status": "OK",
                "reasons": list(candidate.reason_codes),
            }
            for candidate in result.candidates
        ],
    }
