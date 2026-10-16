from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

from sp500_candidate_engine.analytics import weekly_job
from sp500_candidate_engine.analytics.weekly_training import WeeklyTrainingRun


def test_prepare_training_export_materializes_cutoff_fixed_history(
    monkeypatch,
    tmp_path,
) -> None:
    export_run_id = uuid.uuid4()
    captured = {}

    class FakeExportService:
        def __init__(self, database) -> None:
            captured["database"] = database

        def export(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(export_run_id=export_run_id)

    run = WeeklyTrainingRun(
        weekly_run_id=uuid.uuid4(),
        iso_week="2026-W42",
        anchor_session=date(2026, 10, 13),
        model_purpose="SHORT_5D",
        policy_version="weekly-v1",
        input_manifest_id=uuid.uuid4(),
        training_cutoff=datetime(2026, 10, 14, 10, tzinfo=UTC),
        label_maturity_cutoff=date(2026, 10, 13),
        status="PENDING",
    )
    database = object()
    monkeypatch.setenv("TRAINING_WORK_ROOT", str(tmp_path))
    monkeypatch.setattr(weekly_job, "HistoricalQlibExportService", FakeExportService)
    monkeypatch.setattr(weekly_job, "version", lambda _name: "test-qlib")

    export_dir = weekly_job._prepare_training_export(database, run)

    assert captured["database"] is database
    assert captured["start_date"] == run.anchor_session - timedelta(days=730)
    assert captured["end_date"] == run.anchor_session
    assert captured["decision_cutoff"] == run.training_cutoff
    assert captured["require_snapshot_available_by_cutoff"] is True
    assert captured["qlib_version"] == "test-qlib"
    assert export_dir == tmp_path / "qlib" / str(export_run_id)
