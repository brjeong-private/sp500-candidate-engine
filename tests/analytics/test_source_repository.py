import uuid
from datetime import UTC, date, datetime

import pytest

from sp500_candidate_engine.analytics.source_repository import (
    ManifestLineageError,
    ManifestSnapshot,
    SourceRepository,
    validate_manifest_lineage,
)


def _snapshot(
    *,
    dataset: str,
    kind: str,
    role: str,
    precedence: int,
    parent_id: uuid.UUID | None = None,
    coverage_start: date | None = None,
    coverage_end: date | None = None,
) -> ManifestSnapshot:
    return ManifestSnapshot(
        source_snapshot_id=uuid.uuid4(),
        dataset_code=dataset,
        snapshot_kind=kind,
        lineage_role=role,
        precedence=precedence,
        parent_snapshot_id=parent_id,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
    )


def test_manifest_lineage_accepts_full_then_delta_chain() -> None:
    baseline = _snapshot(
        dataset="daily_bar",
        kind="FULL",
        role="BASELINE",
        precedence=0,
    )
    delta = _snapshot(
        dataset="daily_bar",
        kind="DELTA",
        role="DELTA",
        precedence=1,
        parent_id=baseline.source_snapshot_id,
    )

    validate_manifest_lineage((baseline, delta))


def test_manifest_lineage_rejects_delta_with_missing_parent() -> None:
    delta = _snapshot(
        dataset="daily_bar",
        kind="DELTA",
        role="DELTA",
        precedence=1,
        parent_id=uuid.uuid4(),
    )

    with pytest.raises(ManifestLineageError, match="missing parent"):
        validate_manifest_lineage((delta,))


def test_manifest_lineage_rejects_duplicate_precedence() -> None:
    first = _snapshot(
        dataset="daily_bar",
        kind="FULL",
        role="BASELINE",
        precedence=0,
    )
    second = _snapshot(
        dataset="daily_bar",
        kind="DELTA",
        role="DELTA",
        precedence=0,
        parent_id=first.source_snapshot_id,
    )

    with pytest.raises(ManifestLineageError, match="duplicate precedence"):
        validate_manifest_lineage((first, second))


def test_manifest_lineage_accepts_non_overlapping_partitioned_full_snapshots() -> None:
    first = _snapshot(
        dataset="daily_bar",
        kind="FULL",
        role="SINGLE",
        precedence=0,
        coverage_start=date(2026, 1, 2),
        coverage_end=date(2026, 1, 2),
    )
    second = _snapshot(
        dataset="daily_bar",
        kind="FULL",
        role="SINGLE",
        precedence=1,
        coverage_start=date(2026, 1, 5),
        coverage_end=date(2026, 1, 5),
    )

    validate_manifest_lineage((first, second))


class _Cursor:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[dict[str, object]]:
        return self._rows


class _Connection:
    def __init__(self, result_sets: list[list[dict[str, object]]]) -> None:
        self.result_sets = result_sets
        self.sql: list[str] = []
        self.params: list[tuple[object, ...]] = []

    def execute(self, sql: str, params: tuple[object, ...]) -> _Cursor:
        self.sql.append(sql)
        self.params.append(params)
        return _Cursor(self.result_sets.pop(0))


def test_read_bars_is_manifest_and_cutoff_constrained() -> None:
    context_id = uuid.uuid4()
    snapshot_id = uuid.uuid4()
    connection = _Connection(
        [
            [
                {
                    "source_snapshot_id": snapshot_id,
                    "dataset_code": "daily_bar",
                    "snapshot_kind": "FULL",
                    "lineage_role": "SINGLE",
                    "precedence": 0,
                    "parent_snapshot_id": None,
                    "coverage_start": date(2026, 1, 9),
                    "coverage_end": date(2026, 1, 9),
                }
            ],
            [
                {
                    "instrument_id": uuid.uuid4(),
                    "session_date": date(2026, 1, 9),
                    "source_id": 1,
                    "revision_no": 1,
                    "open": 10,
                    "high": 11,
                    "low": 9,
                    "close": 10,
                    "volume": 100,
                    "vwap": 10,
                }
            ],
        ]
    )
    repository = SourceRepository(connection)  # type: ignore[arg-type]

    rows = repository.read_bars(
        execution_context_id=context_id,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 9),
    )

    assert len(rows) == 1
    assert "ops.input_manifest_member" in connection.sql[1]
    assert "market.daily_bar_observation" in connection.sql[1]
    assert "obs.observed_at <= ec.cutoff_at" in connection.sql[1]
    assert connection.params[0][0] == context_id


def test_read_sec_facts_is_manifest_and_cutoff_constrained() -> None:
    context_id = uuid.uuid4()
    issuer_id = uuid.uuid4()
    connection = _Connection([[]])

    SourceRepository(connection).read_sec_facts(  # type: ignore[arg-type]
        execution_context_id=context_id,
        issuer_id=issuer_id,
        period_end_on_or_before=date(2025, 12, 31),
    )

    sql = connection.sql[0]
    assert "ops.input_manifest_member" in sql
    assert "fundamental.fact_observation" in sql
    assert "fact.source_available_at <= ec.cutoff_at" in sql
    assert "filing.accepted_at <= ec.cutoff_at" in sql
    assert "obs.observed_at <= ec.cutoff_at" in sql


def test_read_actions_is_manifest_and_cutoff_constrained() -> None:
    context_id = uuid.uuid4()
    instrument_id = uuid.uuid4()
    connection = _Connection([[]])

    SourceRepository(connection).read_corporate_actions(  # type: ignore[arg-type]
        execution_context_id=context_id,
        instrument_id=instrument_id,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
    )

    sql = connection.sql[0]
    assert "ops.input_manifest_member" in sql
    assert "market.corporate_action_observation" in sql
    assert "action.source_available_at <= ec.cutoff_at" in sql
    assert "obs.observed_at <= ec.cutoff_at" in sql


def test_read_events_enforces_publication_and_observation_cutoff() -> None:
    connection = _Connection([[]])

    SourceRepository(connection).read_events(  # type: ignore[arg-type]
        execution_context_id=uuid.uuid4(),
        instrument_id=uuid.uuid4(),
        event_type="NEWS",
        start_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    sql = connection.sql[0]
    assert "event.event_revision_observation" in sql
    assert "revision.source_available_at <= ec.cutoff_at" in sql
    assert "revision.published_at" in sql
    assert "BETWEEN %s AND ec.cutoff_at" in sql
    assert "obs.observed_at <= ec.cutoff_at" in sql


def test_read_filings_enforces_acceptance_and_observation_cutoff() -> None:
    connection = _Connection([[]])

    SourceRepository(connection).read_sec_filings(  # type: ignore[arg-type]
        execution_context_id=uuid.uuid4(),
        issuer_id=uuid.uuid4(),
        filed_on_or_after=date(2025, 1, 1),
    )

    sql = connection.sql[0]
    assert "fundamental.sec_filing_observation" in sql
    assert "filing.accepted_at <= ec.cutoff_at" in sql
    assert "ss.source_available_at <= ec.cutoff_at" in sql
    assert "obs.observed_at <= ec.cutoff_at" in sql


def test_read_universe_requires_manifested_active_point_in_time_state() -> None:
    connection = _Connection([[]])

    SourceRepository(connection).read_universe_members(  # type: ignore[arg-type]
        execution_context_id=uuid.uuid4(),
        target_session=date(2026, 1, 9),
    )

    sql = connection.sql[0]
    assert "uv.source_snapshot_id = imm.source_snapshot_id" in sql
    assert "state.source_snapshot_id = imm.source_snapshot_id" in sql
    assert "uv.announced_at <= ec.cutoff_at" in sql
    assert "state.observed_at <= ec.cutoff_at" in sql
    assert "state.status IN ('ACTIVE', 'LISTED')" in sql
