import uuid
from datetime import date, datetime

from sp500_candidate_engine.models import UTC
from sp500_candidate_engine.selection.policy import SelectedCandidate, SelectionResult
from sp500_candidate_engine.selection.service import candidate_result_payload


def test_candidate_result_contract_includes_temporal_identity() -> None:
    result = SelectionResult(
        status="SUCCEEDED",
        candidates=(
            SelectedCandidate(
                instrument_id=uuid.UUID(int=1),
                issuer_id=uuid.UUID(int=2),
                symbol="TEST",
                sector="Tech",
                position=1,
                score=0.5,
                rank_overall=1,
                score_percentile=1.0,
                rank_sector=1,
                reason_codes=("MODEL_TOP_RANK",),
            ),
        ),
        soft_constraints_relaxed=("sector_cap",),
    )

    payload = candidate_result_payload(
        selection_run_id=uuid.UUID(int=3),
        scoring_run_id=uuid.UUID(int=4),
        model_version_id=uuid.UUID(int=5),
        execution_context_id=uuid.UUID(int=6),
        price_session_date=date(2026, 10, 8),
        cutoff_at=datetime(2026, 10, 9, 9, 30, tzinfo=UTC),
        generated_at=datetime(2026, 10, 9, 10, 0, tzinfo=UTC),
        policy_version="1",
        result=result,
    )

    assert payload["selection_type"] == "QUANTITATIVE"
    assert payload["model_status"] == "SHADOW"
    assert payload["promotion_gate_passed"] is False
    assert payload["price_session_date"] == "2026-10-08"
    assert payload["candidates"][0]["symbol"] == "TEST"
