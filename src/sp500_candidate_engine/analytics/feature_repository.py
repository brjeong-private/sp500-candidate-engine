from __future__ import annotations

import uuid
from collections.abc import Iterable

from sp500_candidate_engine.analytics.db import execute_many
from sp500_candidate_engine.analytics.labels import DailyLabelValue
from sp500_candidate_engine.database import _canonical_hash, _stable_uuid


def build_feature_run_key(
    *,
    export_run_id: uuid.UUID,
    feature_definition_version_id: uuid.UUID,
    processor_version_id: uuid.UUID | None,
    stage: str,
    code_version: str,
) -> str:
    return _canonical_hash(
        {
            "export_run_id": export_run_id,
            "feature_definition_version_id": feature_definition_version_id,
            "processor_version_id": processor_version_id,
            "stage": stage,
            "code_version": code_version,
        }
    )


def build_label_run_key(
    *,
    execution_context_id: uuid.UUID,
    universe_version_id: uuid.UUID,
    label_definition_version_id: uuid.UUID,
    boundary_policy: dict[str, object],
    code_version: str,
) -> str:
    return _canonical_hash(
        {
            "execution_context_id": execution_context_id,
            "universe_version_id": universe_version_id,
            "label_definition_version_id": label_definition_version_id,
            "boundary_policy": boundary_policy,
            "code_version": code_version,
        }
    )


class FeatureRepository:
    def __init__(self, connection: object) -> None:
        self.connection = connection

    def create_feature_run(
        self,
        *,
        export_run_id: uuid.UUID,
        feature_definition_version_id: uuid.UUID,
        processor_version_id: uuid.UUID | None,
        parent_feature_run_id: uuid.UUID | None,
        stage: str,
        code_version: str,
    ) -> uuid.UUID:
        key = build_feature_run_key(
            export_run_id=export_run_id,
            feature_definition_version_id=feature_definition_version_id,
            processor_version_id=processor_version_id,
            stage=stage,
            code_version=code_version,
        )
        run_id = _stable_uuid("feature-run", key)
        self.connection.execute(  # type: ignore[attr-defined]
            """
            INSERT INTO analytics.feature_run(
                feature_run_id, export_run_id, feature_definition_version_id,
                processor_version_id, parent_feature_run_id, stage,
                code_version, status, idempotency_key
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'RUNNING', %s)
            ON CONFLICT (idempotency_key) DO NOTHING
            """,
            (
                run_id,
                export_run_id,
                feature_definition_version_id,
                processor_version_id,
                parent_feature_run_id,
                stage,
                code_version,
                key,
            ),
        )
        return run_id

    def create_label_run(
        self,
        *,
        execution_context_id: uuid.UUID,
        universe_version_id: uuid.UUID,
        label_definition_version_id: uuid.UUID,
        boundary_policy: dict[str, object],
        code_version: str,
    ) -> uuid.UUID:
        key = build_label_run_key(
            execution_context_id=execution_context_id,
            universe_version_id=universe_version_id,
            label_definition_version_id=label_definition_version_id,
            boundary_policy=boundary_policy,
            code_version=code_version,
        )
        run_id = _stable_uuid("label-run", key)
        self.connection.execute(  # type: ignore[attr-defined]
            """
            INSERT INTO analytics.label_run(
                label_run_id, execution_context_id, universe_version_id,
                label_definition_version_id, code_version, boundary_policy,
                status, idempotency_key
            )
            VALUES (%s, %s, %s, %s, %s, %s, 'RUNNING', %s)
            ON CONFLICT (idempotency_key) DO NOTHING
            """,
            (
                run_id,
                execution_context_id,
                universe_version_id,
                label_definition_version_id,
                code_version,
                boundary_policy,
                key,
            ),
        )
        return run_id

    def write_feature_values(
        self,
        *,
        feature_run_id: uuid.UUID,
        rows: Iterable[
            tuple[uuid.UUID, object, list[float], int, bytes | None, str]
        ],
    ) -> None:
        payload = []
        for instrument_id, session_date, values, missing_count, bitmap, status in rows:
            payload.append(
                (
                    feature_run_id,
                    instrument_id,
                    session_date,
                    values,
                    len(values),
                    missing_count,
                    bitmap,
                    status,
                )
            )
        execute_many(
            self.connection,  # type: ignore[arg-type]
            """
            INSERT INTO analytics.feature_value(
                feature_run_id, instrument_id, session_date, values_real,
                value_count, missing_count, missing_bitmap, quality_status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            payload,
        )

    def write_labels(
        self,
        *,
        label_run_id: uuid.UUID,
        labels: Iterable[DailyLabelValue],
    ) -> None:
        execute_many(
            self.connection,  # type: ignore[arg-type]
            """
            INSERT INTO analytics.daily_label(
                label_run_id, instrument_id, anchor_session_date,
                entry_session_date, exit_session_date, raw_return,
                benchmark_return, label_value, quality_status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            [
                (
                    label_run_id,
                    label.instrument_id,
                    label.anchor_session_date,
                    label.entry_session_date,
                    label.exit_session_date,
                    label.raw_return,
                    label.benchmark_return,
                    label.label_value,
                    label.quality_status,
                )
                for label in labels
            ],
        )

    def complete_feature_run(
        self,
        *,
        feature_run_id: uuid.UUID,
        value_count: int,
    ) -> None:
        self.connection.execute(  # type: ignore[attr-defined]
            """
            UPDATE analytics.feature_run
               SET status = 'SUCCEEDED', value_count = %s, computed_at = now()
             WHERE feature_run_id = %s AND status IN ('RUNNING', 'SUCCEEDED')
            """,
            (value_count, feature_run_id),
        )

    def complete_label_run(self, *, label_run_id: uuid.UUID) -> None:
        self.connection.execute(  # type: ignore[attr-defined]
            """
            UPDATE analytics.label_run
               SET status = 'SUCCEEDED', finished_at = now()
             WHERE label_run_id = %s AND status IN ('RUNNING', 'SUCCEEDED')
            """,
            (label_run_id,),
        )
