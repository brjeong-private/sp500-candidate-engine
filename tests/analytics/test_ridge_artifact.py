import json
import subprocess
import sys
import uuid

import numpy as np
import pandas as pd
import pytest

from backend.app.services.model_artifacts import ArtifactBinding, ModelArtifactLoader
from sp500_candidate_engine.analytics.artifacts import (
    ArtifactManifest,
    ArtifactValidationError,
    load_numeric_ridge,
    package_model_artifact,
    sha256_bytes,
    sha256_file,
)
from sp500_candidate_engine.analytics.baselines import RidgeBaseline
from sp500_candidate_engine.analytics.ridge_artifact import (
    NumericRidge,
    export_fitted_ridge,
    verify_ridge_parity,
)
from tests.analytics.test_artifacts import ROOT, _registered


def test_lightgbm_loader_import_does_not_import_ridge_runtime():
    result = subprocess.run(
        [sys.executable, "-c", (
            "import sys; import backend.app.services.model_artifacts;"
            "assert 'sp500_candidate_engine.analytics.ridge_artifact' not in sys.modules"
        )],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.fixture
def fitted():
    rng = np.random.default_rng(7)
    features = pd.DataFrame(
        rng.normal(size=(80, 158)).astype("float32"),
        columns=[f"f{i}" for i in range(158)],
    )
    features.iloc[:, 0] = np.nan
    features.iloc[:, 1] = 3
    features.iloc[::3, 2] = np.nan
    baseline = RidgeBaseline(10, 42)
    baseline.fit(features, pd.Series(rng.normal(size=80)))
    content = export_fitted_ridge(
        baseline.pipeline, feature_names=tuple(features.columns), training_artifact_sha256="a"*64,
    )
    return baseline, features, content


def test_fitted_numeric_parity_preserves_empty_columns_and_dtypes(fitted):
    baseline, features, content = fitted
    model = NumericRidge.from_bytes(content)
    assert model.statistics[0] == 0
    assert model.scale[0] == model.scale[1] == 1
    result = verify_ridge_parity(baseline.pipeline, model, features)
    assert result["max_absolute_error"] < 1e-6
    assert model.predict(features).dtype == np.float32
    assert model.predict(features.astype("float64")).dtype == np.float64
    assert content == model.to_bytes()


@pytest.mark.parametrize("failure", ["order", "infinite", "object", "empty", "float16"])
def test_bad_inference_inputs_fail_closed(fitted, failure):
    _, features, content = fitted
    if failure == "order":
        features = features[features.columns[::-1]]
    elif failure == "infinite":
        features.iloc[0, 3] = np.inf
    elif failure == "object":
        features = features.astype(str)
    elif failure == "float16":
        features = features.astype("float16")
    else:
        features = features.iloc[:0]
    with pytest.raises(ValueError):
        NumericRidge.from_bytes(content).predict(features)


@pytest.mark.parametrize("failure", ["scale", "dtype", "shape", "processor", "coef", "hash"])
def test_bad_numeric_payload_fail_closed(fitted, failure):
    _, _, content = fitted
    value = json.loads(content)
    if failure == "scale":
        value["scaler"]["scale"][0] = 0
    elif failure == "dtype":
        value["ridge"]["dtype"] = "object"
    elif failure == "shape":
        value["ridge"]["coefficient"].pop()
    elif failure == "processor":
        value["imputer"]["keep_empty_features"] = False
    elif failure == "coef":
        value["ridge"]["coefficient"][0] = float("nan")
    else:
        value["training_artifact_sha256"] = "unbound"
    with pytest.raises(ValueError):
        NumericRidge.from_bytes(json.dumps(value).encode())


def test_schema3_packages_selected_ridge_and_loader_preserves_registered_identity(tmp_path, fitted):
    baseline, features, _ = fitted
    source = tmp_path / "source"
    source.mkdir()
    baseline.save(source / "ridge.joblib")
    digest = sha256_file(source / "ridge.joblib")
    baseline.save_numeric(source / "ridge.json", training_artifact_sha256=digest)
    features.add_prefix("feature::").to_parquet(source / "training_dataset.parquet")
    registered = _registered(b"", "MEDIUM_20D")
    model_id = uuid.uuid4()
    registered.update(model_name="ridge", artifact_hash=digest, model_version_id=model_id)
    with pytest.raises(ArtifactValidationError, match="explicit family admission"):
        package_model_artifact(
            source_directory=source, output_directory=tmp_path / "rejected",
            model_version_id=model_id, model_purpose="MEDIUM_20D", registered_model=registered,
            config_root=ROOT / "config" / "analytics",
        )
    artifact = package_model_artifact(
        source_directory=source, output_directory=tmp_path / "artifact",
        model_version_id=model_id, model_purpose="MEDIUM_20D", registered_model=registered,
        config_root=ROOT / "config" / "analytics",
        allow_ridge=True,
    )
    assert artifact.manifest.schema_version == 3
    assert artifact.manifest.model_version_id == model_id
    assert artifact.manifest.registered_artifact_sha256 == digest
    assert digest != artifact.model_sha256
    loaded = ModelArtifactLoader(tmp_path / "cache").load(ArtifactBinding(
        "MEDIUM_20D", artifact.manifest_path.as_uri(), artifact.manifest_sha256,
    ))
    model = load_numeric_ridge(loaded.manifest, loaded.model_path)
    assert verify_ridge_parity(baseline.pipeline, model, features)["max_absolute_error"] < 1e-6
    value = artifact.manifest.to_dict()
    value["model_family"] = "lightgbm"
    with pytest.raises(ArtifactValidationError):
        ArtifactManifest.from_bytes(json.dumps(value).encode())
    value["model_family"] = "ridge"
    value["model_sha256"] = sha256_bytes(b"tampered")
    with pytest.raises(ArtifactValidationError):
        load_numeric_ridge(
            ArtifactManifest.from_bytes(json.dumps(value).encode()), loaded.model_path,
        )


def test_export_rejects_changed_feature_order_or_processor(fitted):
    baseline, features, _ = fitted
    with pytest.raises(ValueError, match="preprocessing"):
        export_fitted_ridge(
            baseline.pipeline, feature_names=tuple(features.columns[::-1]),
            training_artifact_sha256="a"*64,
        )
    baseline.pipeline.named_steps["imputer"].keep_empty_features = False
    with pytest.raises(ValueError, match="preprocessing"):
        export_fitted_ridge(
            baseline.pipeline, feature_names=tuple(features.columns),
            training_artifact_sha256="a"*64,
        )


@pytest.mark.parametrize("change", ["model_id", "checkpoint", "registered_hash"])
def test_packager_rejects_unbound_checkpoint_identity(tmp_path, fitted, change):
    baseline, features, _ = fitted
    source = tmp_path / "source"
    source.mkdir()
    baseline.save(source / "ridge.joblib")
    digest = sha256_file(source / "ridge.joblib")
    baseline.save_numeric(source / "ridge.json", training_artifact_sha256=digest)
    features.add_prefix("feature::").to_parquet(source / "training_dataset.parquet")
    model_id = uuid.uuid4()
    registered = _registered(b"", "MEDIUM_20D")
    registered.update(model_name="ridge", artifact_hash=digest, model_version_id=model_id)
    if change == "model_id":
        registered["model_version_id"] = uuid.uuid4()
    elif change == "checkpoint":
        (source / "ridge.joblib").write_bytes(b"corrupted")
    else:
        registered["artifact_hash"] = "f" * 64
    with pytest.raises(ArtifactValidationError):
        package_model_artifact(
            source_directory=source, output_directory=tmp_path / "artifact",
            model_version_id=model_id, model_purpose="MEDIUM_20D", registered_model=registered,
            config_root=ROOT / "config" / "analytics", allow_ridge=True,
        )
