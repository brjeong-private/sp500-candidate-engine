from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from sp500_candidate_engine.analytics.artifacts import (
    ArtifactManifest,
    ArtifactValidationError,
    package_model_artifact,
)
from sp500_candidate_engine.analytics.config import load_versioned_config
from sp500_candidate_engine.database import _canonical_hash

ROOT = Path(__file__).parents[2]


def _source(tmp_path: Path) -> tuple[Path, bytes]:
    source = tmp_path / "source"
    source.mkdir()
    weights = b"immutable lightgbm weights"
    (source / "lightgbm.txt").write_bytes(weights)
    fields = {f"feature::f{index}": [float(index)] for index in range(158)}
    pq.write_table(pa.table(fields), source / "training_dataset.parquet")
    return source, weights


def _registered(weights: bytes, purpose: str) -> dict[str, object]:
    analytics = ROOT / "config" / "analytics"
    model_name = (
        "model_lightgbm_v2.yaml"
        if purpose == "SHORT_5D"
        else "model_lightgbm_20d_v1.yaml"
    )
    label_name = (
        "label_forward_return_5d_v2.yaml"
        if purpose == "SHORT_5D"
        else "label_forward_return_20d_v1.yaml"
    )
    model = load_versioned_config(analytics / model_name)
    label = load_versioned_config(analytics / label_name)
    return {
        "model_name": "lightgbm",
        "version": model.payload["version"],
        "artifact_hash": hashlib.sha256(weights).hexdigest(),
        "config_hash": _canonical_hash(
            {
                "model_config_hash": model.config_hash,
                "label_config_hash": label.config_hash,
            }
        ),
        "processor_version_id": None,
        "label_semantics": (
            "RAW_STOCK_5D_RETURN"
            if purpose == "SHORT_5D"
            else "RAW_STOCK_20D_RETURN"
        ),
        "model_purpose": purpose,
        "return_policy": "PRICE_RETURN",
    }


@pytest.mark.parametrize("purpose", ["SHORT_5D", "MEDIUM_20D"])
def test_packages_schema_v2_with_distinct_manifest_and_model_hashes(tmp_path, purpose):
    source, weights = _source(tmp_path)
    output = tmp_path / "output"

    packaged = package_model_artifact(
        source_directory=source,
        output_directory=output,
        model_version_id=uuid.uuid4(),
        model_purpose=purpose,
        registered_model=_registered(weights, purpose),
        config_root=ROOT / "config" / "analytics",
    )
    parsed = ArtifactManifest.from_bytes(
        packaged.manifest_path.read_bytes(), expected_purpose=purpose
    )

    assert parsed.schema_version == 2
    assert parsed.model_sha256 == packaged.model_sha256
    assert packaged.manifest_sha256 == hashlib.sha256(
        packaged.manifest_path.read_bytes()
    ).hexdigest()
    assert packaged.manifest_sha256 != packaged.model_sha256


def test_manifest_is_immutable_and_rejects_cross_purpose(tmp_path):
    source, weights = _source(tmp_path)
    output = tmp_path / "output"
    packaged = package_model_artifact(
        source_directory=source,
        output_directory=output,
        model_version_id=uuid.uuid4(),
        model_purpose="SHORT_5D",
        registered_model=_registered(weights, "SHORT_5D"),
        config_root=ROOT / "config" / "analytics",
    )
    payload = json.loads(packaged.manifest_path.read_bytes())
    payload["model_purpose"] = "MEDIUM_20D"

    with pytest.raises(FileExistsError, match="Immutable artifact"):
        package_model_artifact(
            source_directory=source,
            output_directory=output,
            model_version_id=uuid.uuid4(),
            model_purpose="SHORT_5D",
            registered_model=_registered(weights, "SHORT_5D"),
            config_root=ROOT / "config" / "analytics",
        )
    with pytest.raises(ArtifactValidationError, match="purpose contract"):
        ArtifactManifest.from_bytes(json.dumps(payload).encode())


def test_manifest_rejects_unknown_fields_and_nonlocal_model_file(tmp_path):
    source, weights = _source(tmp_path)
    packaged = package_model_artifact(
        source_directory=source,
        output_directory=tmp_path / "output",
        model_version_id=uuid.uuid4(),
        model_purpose="SHORT_5D",
        registered_model=_registered(weights, "SHORT_5D"),
        config_root=ROOT / "config" / "analytics",
    )
    payload = packaged.manifest.to_dict()
    payload["unexpected"] = True
    with pytest.raises(ArtifactValidationError, match="fields"):
        ArtifactManifest.from_bytes(json.dumps(payload).encode())
    payload.pop("unexpected")
    payload["model_file"] = "../weights.txt"
    with pytest.raises(ArtifactValidationError, match="local file"):
        ArtifactManifest.from_bytes(json.dumps(payload).encode())
