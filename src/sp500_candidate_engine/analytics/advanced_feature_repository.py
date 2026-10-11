from __future__ import annotations

import uuid
from datetime import datetime

from psycopg.types.json import Jsonb

from sp500_candidate_engine.analytics.news_classifier import NewsClassification
from sp500_candidate_engine.analytics.readiness import ExperimentReadiness
from sp500_candidate_engine.database import _canonical_hash, _stable_uuid


class AdvancedFeatureRepository:
    def __init__(self, connection: object) -> None:
        self.connection = connection

    def write_news_classification(
        self, classification: NewsClassification
    ) -> uuid.UUID:
        lineage_key = _canonical_hash(
            {
                "source_snapshot_id": classification.source_snapshot_id,
                "event_revision_id": classification.event_revision_id,
                "input_hash": classification.input_hash,
                "prompt_version": classification.prompt_version,
                "deployment": classification.deployment,
            }
        )
        classification_id = _stable_uuid("news-classification", lineage_key)
        self.connection.execute(  # type: ignore[attr-defined]
            """
            INSERT INTO event.news_event_classification(
                classification_id, source_snapshot_id, event_revision_id,
                status, input_hash, prompt_version, deployment,
                structured_output, output_hash, error_code, classified_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (
                source_snapshot_id, event_revision_id, input_hash,
                prompt_version, deployment
            ) DO NOTHING
            """,
            (
                classification_id,
                classification.source_snapshot_id,
                classification.event_revision_id,
                classification.status,
                classification.input_hash,
                classification.prompt_version,
                classification.deployment,
                (
                    None
                    if classification.structured_output is None
                    else Jsonb(classification.structured_output)
                ),
                classification.output_hash,
                classification.error_code,
                classification.classified_at,
            ),
        )
        return classification_id

    def write_readiness_assessments(
        self,
        *,
        execution_context_id: uuid.UUID,
        assessments: tuple[ExperimentReadiness, ...],
        evidence: dict[str, object],
        assessed_at: datetime,
        code_version: str,
    ) -> tuple[uuid.UUID, ...]:
        result: list[uuid.UUID] = []
        for assessment in assessments:
            key = _canonical_hash(
                {
                    "execution_context_id": execution_context_id,
                    "experiment_code": assessment.experiment_code,
                    "assessed_at": assessed_at,
                    "code_version": code_version,
                }
            )
            assessment_id = _stable_uuid("experiment-readiness", key)
            self.connection.execute(  # type: ignore[attr-defined]
                """
                INSERT INTO analytics.experiment_readiness_assessment(
                    readiness_assessment_id, execution_context_id,
                    experiment_code, status, blocking_reasons, evidence,
                    assessed_at, code_version
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (
                    execution_context_id, experiment_code, assessed_at, code_version
                ) DO NOTHING
                """,
                (
                    assessment_id,
                    execution_context_id,
                    assessment.experiment_code,
                    assessment.status,
                    list(assessment.blocking_reasons),
                    Jsonb(evidence),
                    assessed_at,
                    code_version,
                ),
            )
            result.append(assessment_id)
        return tuple(result)
