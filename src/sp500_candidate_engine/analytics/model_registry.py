from __future__ import annotations

import uuid
from dataclasses import dataclass

from psycopg.types.json import Jsonb

from sp500_candidate_engine.database import _canonical_hash, _stable_uuid


@dataclass(frozen=True)
class ModelRegistration:
    model_name: str
    version: str
    export_run_id: uuid.UUID
    config_hash: str
    split_spec: dict[str, object]
    parameters: dict[str, object]
    artifact_uri: str
    artifact_hash: str
    metrics: dict[str, object]
    label_semantics: str = "RAW_STOCK_5D_RETURN"
    promotion_status: str = "SHADOW"
    training_feature_run_id: uuid.UUID | None = None
    processor_version_id: uuid.UUID | None = None
    label_run_id: uuid.UUID | None = None


def model_version_id(registration: ModelRegistration) -> uuid.UUID:
    key = _canonical_hash(
        {
            "model_name": registration.model_name,
            "version": registration.version,
            "export_run_id": registration.export_run_id,
            "config_hash": registration.config_hash,
            "artifact_hash": registration.artifact_hash,
        }
    )
    return _stable_uuid("model-version", key)


class ModelRegistry:
    def __init__(self, connection: object) -> None:
        self.connection = connection

    def register(self, registration: ModelRegistration) -> uuid.UUID:
        version_id = model_version_id(registration)
        self.connection.execute(  # type: ignore[attr-defined]
            """
            INSERT INTO analytics.model_version(
                model_version_id, model_name, version, export_run_id,
                training_feature_run_id, processor_version_id, label_run_id,
                config_hash, split_spec, parameters, artifact_uri,
                artifact_hash, metrics, promotion_status
                , label_semantics
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (model_name, version, config_hash, export_run_id)
            DO UPDATE SET
                artifact_uri = EXCLUDED.artifact_uri,
                artifact_hash = EXCLUDED.artifact_hash,
                metrics = EXCLUDED.metrics,
                promotion_status = EXCLUDED.promotion_status
                , label_semantics = EXCLUDED.label_semantics
            """,
            (
                version_id,
                registration.model_name,
                registration.version,
                registration.export_run_id,
                registration.training_feature_run_id,
                registration.processor_version_id,
                registration.label_run_id,
                registration.config_hash,
                Jsonb(registration.split_spec),
                Jsonb(registration.parameters),
                registration.artifact_uri,
                registration.artifact_hash,
                Jsonb(registration.metrics),
                registration.promotion_status,
                registration.label_semantics,
            ),
        )
        return version_id
