from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from sp500_candidate_engine.analytics import weekly_job
from sp500_candidate_engine.analytics.promotion import DEFAULT_WEEKLY_POLICY_VERSION
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


@pytest.mark.parametrize("artifact_failure", [False, True])
def test_suspended_policy_records_failed_metric_and_still_requires_artifact_validation(
    monkeypatch, tmp_path, artifact_failure,
):
    run = WeeklyTrainingRun(
        weekly_run_id=uuid.uuid4(), iso_week="2026-W43",
        anchor_session=date(2026, 10, 23), model_purpose="MEDIUM_20D",
        policy_version=DEFAULT_WEEKLY_POLICY_VERSION, input_manifest_id=uuid.uuid4(),
        training_cutoff=datetime(2026, 10, 24, 9, 30, tzinfo=UTC),
        label_maturity_cutoff=date(2026, 10, 23), status="EVALUATED",
    )
    summary = SimpleNamespace(
        model_version_id=uuid.uuid4(), selected_shadow_model="lightgbm",
        experiment_dir=tmp_path / "experiment",
        metrics={"lightgbm": {
            "coverage": 1.0, "test_blocks": 16, "rank_ic_mean": 0.00045954353296819435,
            "fold_rank_ic_median": 0.019064504040206525,
            "net_top_10_return": 0.027974113745364553,
            "max_drawdown_top_10": -0.12100869861822139,
        }},
    )
    connection = MagicMock()
    connection.execute.return_value.fetchone.side_effect = [
        {"model_name": "lightgbm", "version": "test"},
        {"model_version_id": summary.model_version_id},
    ]
    database = MagicMock()
    database.connect.return_value.__enter__.return_value = connection
    repository = MagicMock()
    repository.get_active_assignment.return_value = None
    monkeypatch.setattr(weekly_job, "WeeklyTrainingRepository", lambda _conn: repository)
    packager = MagicMock(return_value=SimpleNamespace(manifest_sha256="a" * 64))
    if artifact_failure:
        packager.side_effect = RuntimeError("Artifact validation failed")
    monkeypatch.setattr(weekly_job, "package_model_artifact", packager)
    uploader = MagicMock(return_value=weekly_job.UploadedArtifact(
        "https://storage.example.test/manifest.json", '"etag"', None,
    ))
    monkeypatch.setattr(weekly_job, "_upload_model_artifact", uploader)
    monkeypatch.setenv("TRAINING_WORK_ROOT", str(tmp_path))
    job = weekly_job.WeeklyTrainingJob(
        database, MagicMock(), repository_root=Path(__file__).parents[2],
    )
    if artifact_failure:
        with pytest.raises(RuntimeError, match="Artifact validation failed"):
            job._evaluate_and_finalize(run=run, summary=summary)
        repository.activate.assert_not_called()
        uploader.assert_not_called()
        return
    evaluation = job._evaluate_and_finalize(run=run, summary=summary)
    assert evaluation.promoted
    repository.activate.assert_called_once()
    decision = next(
        call for call in connection.execute.call_args_list
        if "INSERT INTO analytics.model_promotion_decision" in call.args[0]
    )
    saved = json.loads(decision.args[1][-1])
    assert saved["absolute.rank_ic_mean"]["passed"] is False
    assert saved["absolute.rank_ic_mean"]["enforced"] is False
    assert saved["absolute.coverage"]["enforced"] is True
