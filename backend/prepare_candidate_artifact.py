"""Provision one explicitly selected registered model; never bundle data/output."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import uuid
from pathlib import Path

import pyarrow.parquet as parquet

from sp500_candidate_engine.analytics.config import load_versioned_config
from sp500_candidate_engine.config import Settings
from sp500_candidate_engine.database import Database, _canonical_hash


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-version-id", required=True, type=uuid.UUID)
    parser.add_argument("--source-directory", required=True, type=Path)
    parser.add_argument("--output-directory", required=True, type=Path)
    args = parser.parse_args()
    source = args.source_directory.resolve()
    output = args.output_directory.resolve()
    root = Path(__file__).parents[1]
    weights = source / "lightgbm.txt"
    weight_hash = hashlib.sha256(weights.read_bytes()).hexdigest()
    feature_names = [
        name.removeprefix("feature::")
        for name in parquet.read_schema(source / "training_dataset.parquet").names
        if name.startswith("feature::")
    ]
    feature = load_versioned_config(
        root / "config" / "analytics" / "feature_alpha158_v1.yaml",
        required_keys=("expected_dimension",),
    )
    model = load_versioned_config(
        root / "config" / "analytics" / "model_lightgbm_v2.yaml",
        required_keys=("version",),
    )
    label = load_versioned_config(
        root / "config" / "analytics" / "label_forward_return_5d_v2.yaml",
        required_keys=("horizon_sessions",),
    )
    effective_hash = _canonical_hash(
        {
            "model_config_hash": model.config_hash,
            "label_config_hash": label.config_hash,
        }
    )
    with Database(Settings.from_env()).connect() as connection:
        registered = connection.execute(
            """
            SELECT model_name, version, artifact_hash, config_hash, processor_version_id,
                label_semantics FROM analytics.model_version WHERE model_version_id = %s
            """,
            (args.model_version_id,),
        ).fetchone()
    if (
        registered is None
        or registered["model_name"] != "lightgbm"
        or registered["artifact_hash"] != weight_hash
        or registered["config_hash"] != effective_hash
        or str(registered["version"]) != str(model.payload["version"])
        or registered["processor_version_id"] is not None
        or registered["label_semantics"] != "RAW_STOCK_5D_RETURN"
        or len(feature_names) != int(feature.payload["expected_dimension"])
    ):
        raise ValueError("Selected model, weights, features, or registry contract is incompatible")
    manifest = {
        "schema_version": 1,
        "model_version_id": str(args.model_version_id),
        "model_file": "lightgbm.txt",
        "model_sha256": weight_hash,
        "feature_names": feature_names,
        "feature_config_hash": feature.config_hash,
        "model_config_hash": effective_hash,
    }
    output.mkdir(parents=True, exist_ok=True)
    if output != source:
        shutil.copyfile(weights, output / "lightgbm.txt")
    manifest_path = output / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"model_version_id={args.model_version_id}")
    print(f"manifest={manifest_path}")
    print(f"manifest_sha256={hashlib.sha256(manifest_path.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    main()
