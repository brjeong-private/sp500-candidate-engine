import uuid
from datetime import date

from sp500_candidate_engine.selection.repository import selection_run_identity


def test_selection_run_identity_is_idempotent_and_policy_bound() -> None:
    scoring_run_id = uuid.uuid4()

    first = selection_run_identity(
        price_session_date=date(2026, 10, 8),
        scoring_run_id=scoring_run_id,
        policy_version="1",
    )
    second = selection_run_identity(
        price_session_date=date(2026, 10, 8),
        scoring_run_id=scoring_run_id,
        policy_version="1",
    )
    changed = selection_run_identity(
        price_session_date=date(2026, 10, 8),
        scoring_run_id=scoring_run_id,
        policy_version="2",
    )

    assert first == second
    assert first != changed
