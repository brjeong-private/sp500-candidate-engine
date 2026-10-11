import uuid
from datetime import UTC, datetime

from sp500_candidate_engine.analytics.advanced_feature_repository import (
    AdvancedFeatureRepository,
)
from sp500_candidate_engine.analytics.news_classifier import NewsClassification
from sp500_candidate_engine.analytics.readiness import ExperimentReadiness


class _Connection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, sql: str, params: tuple[object, ...]) -> None:
        self.calls.append((sql, params))


def test_repository_persists_immutable_news_lineage() -> None:
    connection = _Connection()
    classification = NewsClassification(
        source_snapshot_id=uuid.uuid4(),
        event_revision_id=uuid.uuid4(),
        status="SUCCEEDED",
        input_hash="input-hash",
        prompt_version="prompt-v1",
        deployment="classifier",
        structured_output={"labels": ["OTHER"], "material": False},
        output_hash="output-hash",
        classified_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    first = AdvancedFeatureRepository(connection).write_news_classification(
        classification
    )
    second = AdvancedFeatureRepository(connection).write_news_classification(
        classification
    )

    assert first == second
    assert "source_snapshot_id" in connection.calls[0][0]
    assert "ON CONFLICT" in connection.calls[0][0]
    assert classification.input_hash in connection.calls[0][1]
    assert classification.output_hash in connection.calls[0][1]


def test_repository_persists_explicit_blocking_results() -> None:
    connection = _Connection()
    context_id = uuid.uuid4()

    ids = AdvancedFeatureRepository(connection).write_readiness_assessments(
        execution_context_id=context_id,
        assessments=(
            ExperimentReadiness(
                experiment_code="E4",
                status="BLOCKED",
                blocking_reasons=("P3_POINT_IN_TIME_MARKET_CAP_UNAVAILABLE",),
            ),
        ),
        evidence={"point_in_time_market_cap_ready": False},
        assessed_at=datetime(2026, 1, 1, tzinfo=UTC),
        code_version="test",
    )

    assert len(ids) == 1
    assert "analytics.experiment_readiness_assessment" in connection.calls[0][0]
    assert connection.calls[0][1][3] == "BLOCKED"
