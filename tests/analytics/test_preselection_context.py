import uuid
from datetime import UTC, date, datetime
from unittest.mock import MagicMock

import pytest

from sp500_candidate_engine.analytics.historical_export import (
    HistoricalInputContext,
    HistoricalQlibExportService,
)
from sp500_candidate_engine.analytics.source_repository import SourceRepository


def test_preselection_manifest_preparation_retains_non_price_evidence():
    target = date(2026, 10, 14)
    cutoff = datetime(2026, 10, 15, 9, 30, tzinfo=UTC)
    universe_id = uuid.uuid4()
    snapshots = [
        {
            "source_snapshot_id": uuid.uuid4(),
            "dataset_code": code,
            "snapshot_kind": "FULL",
            "parent_snapshot_id": None,
            "coverage_start": target,
            "coverage_end": target,
            "cutoff_at": cutoff,
        }
        for code in ("massive_grouped_daily", "massive_news", "sp500_universe")
    ]
    dependency = {
        **snapshots[0],
        "source_snapshot_id": uuid.uuid4(),
        "dataset_code": "massive_ticker_details",
    }
    connection = MagicMock()

    def execute(sql, params):
        result = MagicMock()
        if "WITH ranked_contexts" in sql:
            assert "(%s::boolean OR ss.dataset_code = ANY(%s::text[]))" in sql
            assert params[7] is True
            result.fetchall.return_value = snapshots
        elif "SELECT uv.universe_version_id" in sql:
            result.fetchone.return_value = {"universe_version_id": universe_id}
        elif "WITH evidence_dependencies" in sql:
            assert "ref.instrument_state" in sql
            assert "fundamental.fact_observation" in sql
            assert "snapshot.source_available_at <= %s" in sql
            assert params[-1] == cutoff
            result.fetchall.return_value = [dependency]
        return result

    connection.execute.side_effect = execute
    database = MagicMock()
    database.connect.return_value.__enter__.return_value = connection
    service = HistoricalQlibExportService(database)
    result = service.prepare_preselection_context(
        start_date=target, end_date=target, decision_cutoff=cutoff
    )

    assert result.universe_version_id == universe_id
    assert result.cutoff_at == cutoff
    cursor = connection.cursor.return_value.__enter__.return_value
    rows = list(cursor.executemany.call_args.args[1])
    expected = [*snapshots, dependency]
    assert {row[2] for row in rows} == {row["dataset_code"] for row in expected}
    assert {row[1] for row in rows} == {row["source_snapshot_id"] for row in expected}


def test_qlib_export_rejects_prepared_context_with_different_cutoff(monkeypatch, tmp_path):
    cutoff = datetime(2026, 10, 15, 9, 30, tzinfo=UTC)
    prepared = HistoricalInputContext(uuid.uuid4(), uuid.uuid4(), cutoff)
    monkeypatch.setattr(
        SourceRepository,
        "read_context",
        lambda *args, **kwargs: {"cutoff_at": cutoff},
    )
    service = HistoricalQlibExportService(MagicMock())

    with pytest.raises(ValueError, match="cutoff mismatch"):
        service.export(
            start_date=date(2026, 10, 14),
            end_date=date(2026, 10, 14),
            output_root=tmp_path,
            qlib_version="test",
            decision_cutoff=datetime(2026, 10, 16, 9, 30, tzinfo=UTC),
            input_context=prepared,
        )
