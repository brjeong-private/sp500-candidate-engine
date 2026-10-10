import uuid

from sp500_candidate_engine.analytics.export_repository import (
    build_export_idempotency_key,
)


def test_export_idempotency_key_is_deterministic_and_policy_sensitive() -> None:
    context_id = uuid.uuid4()
    universe_id = uuid.uuid4()

    first = build_export_idempotency_key(
        execution_context_id=context_id,
        universe_version_id=universe_id,
        start_date="2026-01-01",
        end_date="2026-01-31",
        adjustment_policy="SPLIT_ONLY",
        exporter_version="1",
    )
    second = build_export_idempotency_key(
        execution_context_id=context_id,
        universe_version_id=universe_id,
        start_date="2026-01-01",
        end_date="2026-01-31",
        adjustment_policy="SPLIT_ONLY",
        exporter_version="1",
    )
    total_return = build_export_idempotency_key(
        execution_context_id=context_id,
        universe_version_id=universe_id,
        start_date="2026-01-01",
        end_date="2026-01-31",
        adjustment_policy="TOTAL_RETURN",
        exporter_version="1",
    )

    assert first == second
    assert first != total_return
