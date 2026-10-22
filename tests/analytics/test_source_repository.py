import sqlite3
import uuid
from datetime import UTC, date, datetime, timedelta

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


class _UniverseConnection:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.sql: list[str] = []

    def execute(self, sql: str, params: tuple[object, ...]) -> _Cursor:
        self.sql.append(sql)
        values = tuple(
            value.isoformat() if isinstance(value, (date, datetime)) else str(value)
            for value in params
        )
        rows = self.connection.execute(sql.replace("%s", "?"), values).fetchall()
        return _Cursor([dict(row) for row in rows])


@pytest.mark.parametrize(
    ("field", "offset", "mode", "in_manifest", "expected"),
    [
        ("effective_at", 108, "HISTORICAL_RECONSTRUCTION", True, "old"),
        ("effective_at", 1, "HISTORICAL_RECONSTRUCTION", True, "old"),
        ("effective_at", 0, "HISTORICAL_RECONSTRUCTION", True, "new"),
        ("effective_at", -1, "HISTORICAL_RECONSTRUCTION", True, "new"),
        ("announced_at", 1, "HISTORICAL_RECONSTRUCTION", True, "old"),
        ("source_available_at", 1, "HISTORICAL_RECONSTRUCTION", True, "old"),
        ("as_of_date", 1, "HISTORICAL_RECONSTRUCTION", True, "old"),
        ("fetched_at", 1, "OPERATIONAL_REPLAY", True, "old"),
        ("fetched_at", 0, "OPERATIONAL_REPLAY", True, "new"),
        ("fetched_at", 1, "HISTORICAL_RECONSTRUCTION", True, "new"),
        ("effective_at", 0, "HISTORICAL_RECONSTRUCTION", False, "old"),
    ],
)
def test_universe_version_and_member_queries_share_temporal_selection(
    monkeypatch, field, offset, mode, in_manifest, expected,
):
    monkeypatch.setattr(
        "sp500_candidate_engine.analytics.research_eligibility.read_research_members",
        lambda *args, **kwargs: None,
    )
    cutoff = datetime(2026, 10, 22, 9, 30, tzinfo=UTC)
    target = date(2026, 10, 21)
    context_id = uuid.uuid4()
    with sqlite3.connect(":memory:") as connection:
        connection.row_factory = sqlite3.Row
        connection.executescript("""
            ATTACH DATABASE ':memory:' AS ops;
            ATTACH DATABASE ':memory:' AS ref;
            CREATE TABLE ops.execution_context (
                execution_context_id TEXT, input_manifest_id TEXT,
                cutoff_at TEXT, knowledge_mode TEXT
            );
            CREATE TABLE ops.input_manifest_member (
                input_manifest_id TEXT, source_snapshot_id TEXT, precedence INTEGER
            );
            CREATE TABLE ops.source_snapshot (
                source_snapshot_id TEXT, source_available_at TEXT, fetched_at TEXT
            );
            CREATE TABLE ref.universe_version (
                universe_version_id TEXT, source_snapshot_id TEXT, as_of_date TEXT,
                announced_at TEXT, effective_at TEXT
            );
            CREATE TABLE ref.universe_member (
                universe_version_id TEXT, instrument_id TEXT, symbol TEXT,
                security_name TEXT, sector TEXT, sub_industry TEXT
            );
            CREATE TABLE ref.instrument (instrument_id TEXT, issuer_id TEXT);
            CREATE TABLE ref.instrument_state (
                instrument_id TEXT, source_snapshot_id TEXT, revision_no INTEGER,
                valid_from TEXT, valid_to TEXT, source_available_at TEXT, observed_at TEXT,
                primary_exchange TEXT, status TEXT, instrument_state_id TEXT
            );
        """)
        connection.execute(
            "INSERT INTO ops.execution_context VALUES (?, 'manifest', ?, ?)",
            (str(context_id), cutoff.isoformat(), mode),
        )
        connection.execute("INSERT INTO ref.instrument VALUES ('instrument', 'issuer')")
        for version in ("old", "new"):
            values = {
                "as_of_date": target.isoformat(),
                "announced_at": (cutoff - timedelta(days=1)).isoformat(),
                "effective_at": (
                    cutoff - timedelta(days=7) if version == "old" else cutoff
                ).isoformat(),
                "source_available_at": (cutoff - timedelta(days=1)).isoformat(),
                "fetched_at": cutoff.isoformat(),
            }
            if version == "new":
                values[field] = (
                    (target + timedelta(days=offset)).isoformat()
                    if field == "as_of_date" else
                    (cutoff + timedelta(seconds=offset)).isoformat()
                )
            if version == "old" or in_manifest:
                connection.execute(
                    "INSERT INTO ops.input_manifest_member VALUES ('manifest', ?, 0)", (version,),
                )
            connection.execute(
                "INSERT INTO ops.source_snapshot VALUES (?, ?, ?)",
                (version, values["source_available_at"], values["fetched_at"]),
            )
            connection.execute(
                "INSERT INTO ref.universe_version VALUES (?, ?, ?, ?, ?)",
                (version, version, values["as_of_date"],
                 values["announced_at"], values["effective_at"]),
            )
            connection.execute(
                "INSERT INTO ref.universe_member VALUES (?, 'instrument', 'TEST', "
                "'Test Company', 'Sector', 'Industry')", (version,),
            )
        connection.execute(
            "INSERT INTO ref.instrument_state VALUES "
            "('instrument', 'old', 1, '2026-01-01', NULL, ?, ?, 'XNYS', 'ACTIVE', 'state')",
            ((cutoff - timedelta(days=1)).isoformat(), cutoff.isoformat()),
        )
        adapter = _UniverseConnection(connection)
        repository = SourceRepository(adapter)
        version = repository.read_universe_version(
            execution_context_id=context_id, target_session=target,
        )
        members = repository.read_universe_members(
            execution_context_id=context_id, target_session=target,
        )
        assert version is not None
        assert version["universe_version_id"] == expected
        assert len(members) == 1
        assert members[0]["universe_version_id"] == expected
        assert adapter.sql[0].split("SELECT * FROM eligible_versions")[0] == (
            adapter.sql[1].split(", current_state AS")[0]
        )


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
    connection = _Connection([[], []])

    SourceRepository(connection).read_universe_members(  # type: ignore[arg-type]
        execution_context_id=uuid.uuid4(),
        target_session=date(2026, 1, 9),
    )

    sql = connection.sql[1]
    assert "uv.source_snapshot_id = imm.source_snapshot_id" in sql
    assert "state.source_snapshot_id = imm.source_snapshot_id" in sql
    assert "uv.announced_at <= ec.cutoff_at" in sql
    assert "state.observed_at <= ec.cutoff_at" in sql
    assert "state.status IN ('ACTIVE', 'LISTED')" in sql
