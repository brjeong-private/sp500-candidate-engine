from backend import grant_weekly_training_access


def test_weekly_training_grants_limit_source_writes_to_derived_context_metadata() -> None:
    assert grant_weekly_training_access.WRITE_SCHEMA == "analytics"
    assert "analytics" not in grant_weekly_training_access.READ_SCHEMAS
    assert "selection" in grant_weekly_training_access.READ_SCHEMAS
    assert grant_weekly_training_access.DERIVED_OPS_TABLES == (
        "input_manifest",
        "input_manifest_member",
        "execution_context",
    )
