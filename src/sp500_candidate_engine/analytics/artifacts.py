from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

import pyarrow.parquet as parquet

from sp500_candidate_engine.analytics.config import load_versioned_config
from sp500_candidate_engine.database import _canonical_hash

MANIFEST_SCHEMA_VERSION = 2
MANIFEST_FILE_NAME = "manifest.json"
MODEL_FILE_NAME = "lightgbm.txt"
SHA256_LENGTH = 64


@dataclass(frozen=True)
class ModelPurposeContract:
    model_config: str
    label_config: str
    label_semantics: str
    prediction_semantics: str
    horizon_sessions: int


MODEL_PURPOSES: Mapping[str, ModelPurposeContract] = MappingProxyType(
    {
        "SHORT_5D": ModelPurposeContract(
            model_config="model_lightgbm_v2.yaml",
            label_config="label_forward_return_5d_v2.yaml",
            label_semantics="RAW_STOCK_5D_RETURN",
            prediction_semantics="PREDICTED_5D_RETURN",
            horizon_sessions=5,
        ),
        "MEDIUM_20D": ModelPurposeContract(
            model_config="model_lightgbm_20d_v1.yaml",
            label_config="label_forward_return_20d_v1.yaml",
            label_semantics="RAW_STOCK_20D_RETURN",
            prediction_semantics="PREDICTED_20D_RETURN",
            horizon_sessions=20,
        ),
    }
)


class ArtifactValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ArtifactManifest:
    schema_version: int
    model_purpose: str
    label_semantics: str
    prediction_semantics: str
    horizon_sessions: int
    model_version_id: uuid.UUID
    model_file: str
    model_sha256: str
    feature_names: tuple[str, ...]
    feature_config_hash: str
    model_config_hash: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "model_purpose": self.model_purpose,
            "label_semantics": self.label_semantics,
            "prediction_semantics": self.prediction_semantics,
            "horizon_sessions": self.horizon_sessions,
            "model_version_id": str(self.model_version_id),
            "model_file": self.model_file,
            "model_sha256": self.model_sha256,
            "feature_names": list(self.feature_names),
            "feature_config_hash": self.feature_config_hash,
            "model_config_hash": self.model_config_hash,
        }

    def to_bytes(self) -> bytes:
        return (json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n").encode()

    @classmethod
    def from_bytes(
        cls,
        content: bytes,
        *,
        expected_purpose: str | None = None,
    ) -> ArtifactManifest:
        try:
            payload = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ArtifactValidationError("Artifact manifest is not valid UTF-8 JSON") from exc
        if not isinstance(payload, dict):
            raise ArtifactValidationError("Artifact manifest must be a JSON object")
        expected_keys = {
            "schema_version",
            "model_purpose",
            "label_semantics",
            "prediction_semantics",
            "horizon_sessions",
            "model_version_id",
            "model_file",
            "model_sha256",
            "feature_names",
            "feature_config_hash",
            "model_config_hash",
        }
        if set(payload) != expected_keys:
            raise ArtifactValidationError("Artifact manifest schema-v2 fields do not match")
        if not isinstance(payload["feature_names"], list):
            raise ArtifactValidationError("Artifact feature_names must be a JSON array")
        try:
            manifest = cls(
                schema_version=int(payload["schema_version"]),
                model_purpose=str(payload["model_purpose"]),
                label_semantics=str(payload["label_semantics"]),
                prediction_semantics=str(payload["prediction_semantics"]),
                horizon_sessions=int(payload["horizon_sessions"]),
                model_version_id=uuid.UUID(str(payload["model_version_id"])),
                model_file=str(payload["model_file"]),
                model_sha256=str(payload["model_sha256"]),
                feature_names=tuple(payload["feature_names"]),
                feature_config_hash=str(payload["feature_config_hash"]),
                model_config_hash=str(payload["model_config_hash"]),
            )
        except (TypeError, ValueError, AttributeError) as exc:
            raise ArtifactValidationError("Artifact manifest has invalid field types") from exc
        manifest.validate(expected_purpose=expected_purpose)
        return manifest

    def validate(self, *, expected_purpose: str | None = None) -> None:
        if self.schema_version != MANIFEST_SCHEMA_VERSION:
            raise ArtifactValidationError("Only artifact manifest schema version 2 is supported")
        contract = MODEL_PURPOSES.get(self.model_purpose)
        if contract is None:
            raise ArtifactValidationError(f"Unsupported model purpose: {self.model_purpose}")
        if expected_purpose is not None and self.model_purpose != expected_purpose:
            raise ArtifactValidationError("Artifact manifest model purpose mismatch")
        if (
            self.label_semantics != contract.label_semantics
            or self.prediction_semantics != contract.prediction_semantics
            or self.horizon_sessions != contract.horizon_sessions
        ):
            raise ArtifactValidationError("Artifact manifest purpose contract mismatch")
        if (
            not self.model_file
            or Path(self.model_file).name != self.model_file
            or "\\" in self.model_file
        ):
            raise ArtifactValidationError("Artifact model_file must name a local file")
        for name, value in (
            ("model_sha256", self.model_sha256),
            ("feature_config_hash", self.feature_config_hash),
            ("model_config_hash", self.model_config_hash),
        ):
            if (
                len(value) != SHA256_LENGTH
                or value.lower() != value
                or any(character not in "0123456789abcdef" for character in value)
            ):
                raise ArtifactValidationError(f"Artifact {name} must be a lowercase SHA256")
        if (
            not self.feature_names
            or len(set(self.feature_names)) != len(self.feature_names)
            or any(not isinstance(name, str) or not name for name in self.feature_names)
        ):
            raise ArtifactValidationError("Artifact feature_names must be non-empty and unique")


@dataclass(frozen=True)
class PackagedArtifact:
    manifest: ArtifactManifest
    manifest_path: Path
    model_path: Path
    manifest_sha256: str
    model_sha256: str


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_immutable(path: Path, content: bytes) -> None:
    if path.exists():
        if path.read_bytes() != content:
            raise FileExistsError(
                f"Immutable artifact already exists with different content: {path}"
            )
        return
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def package_model_artifact(
    *,
    source_directory: Path,
    output_directory: Path,
    model_version_id: uuid.UUID,
    model_purpose: str,
    registered_model: Mapping[str, object],
    config_root: Path,
) -> PackagedArtifact:
    contract = MODEL_PURPOSES.get(model_purpose)
    if contract is None:
        raise ArtifactValidationError(f"Unsupported model purpose: {model_purpose}")
    source = Path(source_directory).resolve()
    output = Path(output_directory).resolve()
    weights = source / MODEL_FILE_NAME
    model_hash = sha256_file(weights)
    feature_names = tuple(
        name.removeprefix("feature::")
        for name in parquet.read_schema(source / "training_dataset.parquet").names
        if name.startswith("feature::")
    )
    config_root = Path(config_root)
    feature = load_versioned_config(
        config_root / "feature_alpha158_v1.yaml",
        required_keys=("expected_dimension",),
    )
    model = load_versioned_config(
        config_root / contract.model_config,
        required_keys=("version", "prediction_semantics"),
    )
    label = load_versioned_config(
        config_root / contract.label_config,
        required_keys=("horizon_sessions",),
    )
    effective_hash = _canonical_hash(
        {
            "model_config_hash": model.config_hash,
            "label_config_hash": label.config_hash,
        }
    )
    if (
        registered_model.get("model_name") != "lightgbm"
        or registered_model.get("artifact_hash") != model_hash
        or registered_model.get("config_hash") != effective_hash
        or str(registered_model.get("version")) != str(model.payload["version"])
        or registered_model.get("processor_version_id") is not None
        or registered_model.get("label_semantics") != contract.label_semantics
        or registered_model.get("model_purpose") != model_purpose
        or registered_model.get("return_policy") != "PRICE_RETURN"
        or model.payload.get("model_purpose", model_purpose) != model_purpose
        or model.payload.get("return_policy", "PRICE_RETURN") != "PRICE_RETURN"
        or model.payload["prediction_semantics"] != contract.prediction_semantics
        or int(label.payload["horizon_sessions"]) != contract.horizon_sessions
        or len(feature_names) != int(feature.payload["expected_dimension"])
    ):
        raise ArtifactValidationError(
            "Selected model, weights, features, or registry contract is incompatible"
        )
    manifest = ArtifactManifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        model_purpose=model_purpose,
        label_semantics=contract.label_semantics,
        prediction_semantics=contract.prediction_semantics,
        horizon_sessions=contract.horizon_sessions,
        model_version_id=model_version_id,
        model_file=MODEL_FILE_NAME,
        model_sha256=model_hash,
        feature_names=feature_names,
        feature_config_hash=feature.config_hash,
        model_config_hash=effective_hash,
    )
    manifest.validate(expected_purpose=model_purpose)
    manifest_bytes = manifest.to_bytes()
    output.mkdir(parents=True, exist_ok=True)
    output_model = output / MODEL_FILE_NAME
    if output != source:
        if output_model.exists() and sha256_file(output_model) != model_hash:
            raise FileExistsError(
                f"Immutable artifact already exists with different content: {output_model}"
            )
        if not output_model.exists():
            temporary = output / f".{MODEL_FILE_NAME}.{uuid.uuid4().hex}.tmp"
            try:
                shutil.copyfile(weights, temporary)
                if sha256_file(temporary) != model_hash:
                    raise ArtifactValidationError("Copied model checksum mismatch")
                os.replace(temporary, output_model)
            finally:
                temporary.unlink(missing_ok=True)
    _write_immutable(output / MANIFEST_FILE_NAME, manifest_bytes)
    return PackagedArtifact(
        manifest=manifest,
        manifest_path=output / MANIFEST_FILE_NAME,
        model_path=output_model,
        manifest_sha256=sha256_bytes(manifest_bytes),
        model_sha256=model_hash,
    )
