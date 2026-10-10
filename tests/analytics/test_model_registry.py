import uuid

from sp500_candidate_engine.analytics.model_registry import (
    ModelRegistration,
    model_version_id,
)


def test_model_version_identity_is_artifact_and_config_bound() -> None:
    registration = ModelRegistration(
        model_name="lightgbm",
        version="1",
        export_run_id=uuid.uuid4(),
        config_hash="config",
        split_spec={"fold": 1},
        parameters={"seed": 42},
        artifact_uri="file:///model.txt",
        artifact_hash="artifact",
        metrics={"rank_ic_mean": 0.1},
    )

    assert model_version_id(registration) == model_version_id(registration)
    changed = ModelRegistration(
        **{
            **registration.__dict__,
            "artifact_hash": "different",
        }
    )
    assert model_version_id(registration) != model_version_id(changed)
