"""Provision one explicitly selected registered model; never bundle data/output."""

from __future__ import annotations

import argparse
import uuid
from pathlib import Path

from sp500_candidate_engine.analytics.artifacts import (
    MODEL_PURPOSES,
    package_model_artifact,
)
from sp500_candidate_engine.config import Settings
from sp500_candidate_engine.database import Database


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-version-id", required=True, type=uuid.UUID)
    parser.add_argument("--model-purpose", required=True, choices=tuple(MODEL_PURPOSES))
    parser.add_argument("--source-directory", required=True, type=Path)
    parser.add_argument("--output-directory", required=True, type=Path)
    parser.add_argument("--allow-ridge", action="store_true")
    args = parser.parse_args()
    source = args.source_directory.resolve()
    output = args.output_directory.resolve()
    root = Path(__file__).parents[1]
    with Database(Settings.from_env()).connect() as connection:
        registered = connection.execute(
            """
            SELECT model_version_id, model_name, version, artifact_hash, config_hash,
                processor_version_id,
                label_semantics, model_purpose, return_policy
            FROM analytics.model_version WHERE model_version_id = %s
            """,
            (args.model_version_id,),
        ).fetchone()
    if registered is None:
        raise ValueError("Selected model is not registered")
    artifact = package_model_artifact(
        source_directory=source,
        output_directory=output,
        model_version_id=args.model_version_id,
        model_purpose=args.model_purpose,
        registered_model=registered,
        config_root=root / "config" / "analytics",
        allow_ridge=args.allow_ridge,
    )
    print(f"model_version_id={args.model_version_id}")
    print(f"manifest={artifact.manifest_path}")
    print(f"manifest_sha256={artifact.manifest_sha256}")
    print(f"model_sha256={artifact.model_sha256}")


if __name__ == "__main__":
    main()
