import uuid

from sp500_candidate_engine.analytics.feature_repository import (
    build_feature_run_key,
    build_label_run_key,
)


def test_feature_run_key_changes_with_processor() -> None:
    export_run_id = uuid.uuid4()
    definition_id = uuid.uuid4()

    raw = build_feature_run_key(
        export_run_id=export_run_id,
        feature_definition_version_id=definition_id,
        processor_version_id=None,
        stage="RAW",
        code_version="1",
    )
    processed = build_feature_run_key(
        export_run_id=export_run_id,
        feature_definition_version_id=definition_id,
        processor_version_id=uuid.uuid4(),
        stage="PROCESSED",
        code_version="1",
    )

    assert raw != processed


def test_label_run_key_is_policy_sensitive() -> None:
    context_id = uuid.uuid4()
    universe_id = uuid.uuid4()
    definition_id = uuid.uuid4()

    first = build_label_run_key(
        execution_context_id=context_id,
        universe_version_id=universe_id,
        label_definition_version_id=definition_id,
        boundary_policy={"purge": "label_exit"},
        code_version="1",
    )
    second = build_label_run_key(
        execution_context_id=context_id,
        universe_version_id=universe_id,
        label_definition_version_id=definition_id,
        boundary_policy={"purge": "none"},
        code_version="1",
    )

    assert first != second
