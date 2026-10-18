import json
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest

from sp500_candidate_engine.analytics import historical_training as module
from sp500_candidate_engine.analytics import historical_training_context as context_module
from sp500_candidate_engine.analytics import phase45_workflow as workflow
from sp500_candidate_engine.analytics.artifacts import ArtifactManifest
from sp500_candidate_engine.analytics.config import load_versioned_config
from sp500_candidate_engine.analytics.historical_safety import (
    HistoricalSafetyError,
    HistoricalTrainingFence,
)
from sp500_candidate_engine.analytics.historical_training import (
    ReconstructionRequest,
    _isolated_context,
    _validate_sources,
    preceding_weekend_anchor,
    reconstruct_challenger,
    validate_reconstructed_artifact,
)
from sp500_candidate_engine.analytics.phase45_workflow import (
    PreparedTrainingData,
    TrainingWorkflowSummary,
    validate_reconstruction_data,
)
from sp500_candidate_engine.analytics.source_repository import ManifestSnapshot
from sp500_candidate_engine.database import _canonical_hash

ROOT = Path(__file__).resolve().parents[2]
CUTOFF = datetime(2026, 9, 26, 9, 30, tzinfo=UTC)
METRICS = {
    "coverage": 0.9, "test_blocks": 3, "rank_ic_mean": -0.1,
    "fold_rank_ic_median": -0.1, "net_top_10_return": -0.1,
    "max_drawdown_top_10": -0.9,
}


def request() -> ReconstructionRequest:
    return ReconstructionRequest(
        uuid.uuid4(), date(2026, 9, 30), date(2026, 9, 25), CUTOFF,
        uuid.uuid4(), uuid.uuid4(), "a" * 64, "b" * 64, uuid.uuid4(),
    )


def connection_for(
    monkeypatch: pytest.MonkeyPatch, req: ReconstructionRequest,
) -> MagicMock:
    source = MagicMock()
    source.read_context.return_value = {
        "input_manifest_id": req.input_manifest_id, "context_hash": req.context_hash,
        "cutoff_at": req.training_cutoff, "knowledge_mode": "HISTORICAL_RECONSTRUCTION",
    }
    monkeypatch.setattr(module, "SourceRepository", MagicMock(return_value=source))
    connection = MagicMock()
    connection.execute.return_value.fetchall.return_value = [{
        "source_snapshot_id": uuid.uuid4(), "source_available_at": CUTOFF,
        "coverage_end": req.anchor_session, "blocking": False,
        "fetched_at": CUTOFF + timedelta(days=10),
    }]
    connection.execute.return_value.fetchone.return_value = {
        "manifest_hash": req.manifest_hash, "violations": 0, "future_universe": False,
        "ambiguous_universe": False,
        "source_available_at_max": CUTOFF,
        "universe_version_id": req.universe_version_id,
    }
    return connection


@pytest.mark.parametrize(("signal", "anchor"), [
    ("2026-09-30", "2026-09-25"), ("2026-10-01", "2026-09-25"),
    ("2026-10-02", "2026-09-25"), ("2026-10-05", "2026-10-02"),
    ("2026-10-06", "2026-10-02"), ("2026-10-07", "2026-10-02"),
    ("2026-10-08", "2026-10-02"), ("2026-10-09", "2026-10-02"),
    ("2026-10-12", "2026-10-09"), ("2026-10-13", "2026-10-09"),
    ("2026-10-14", "2026-10-09"),
])
def test_historical_anchor_is_not_weekend_iso_week(signal: str, anchor: str) -> None:
    assert preceding_weekend_anchor(date.fromisoformat(signal)) == date.fromisoformat(anchor)


@pytest.mark.parametrize("changes", [
    {"anchor_session": date(2026, 10, 2)},
    {"training_cutoff": datetime(2026, 9, 28, 4, tzinfo=UTC)},
    {"training_cutoff": CUTOFF.replace(tzinfo=None)},
    {"manifest_hash": ""},
])
def test_request_rejects_unsafe_or_implicit_binding(changes: dict[str, object]) -> None:
    with pytest.raises(HistoricalSafetyError):
        replace(request(), **changes).validate()


def test_new_sunday_context_is_allowed_without_moving_friday_data_anchor() -> None:
    sunday = replace(
        request(), anchor_session=date(2026, 10, 9), signal_session=date(2026, 10, 12),
        training_cutoff=datetime(2026, 10, 11, 9, 30, tzinfo=UTC),
    )
    sunday.validate()
    assert sunday.anchor_session == date(2026, 10, 9)
    assert sunday.training_cutoff.date() == date(2026, 10, 11)
    with pytest.raises(HistoricalSafetyError, match="preceding-weekend"):
        replace(
            sunday, training_cutoff=datetime(2026, 10, 12, 4, tzinfo=UTC),
        ).validate()


@pytest.mark.parametrize(("change", "error"), [
    ({"source_available_at": CUTOFF + timedelta(seconds=1)}, "future source snapshot"),
    ({"coverage_end": date(2026, 9, 28)}, "coverage exceeds"),
    ({"blocking": True}, "blocking quality"),
])
def test_frozen_sources_reject_future_and_blocking(
    monkeypatch: pytest.MonkeyPatch, change: dict[str, object], error: str,
) -> None:
    req = request()
    connection = connection_for(monkeypatch, req)
    row = connection.execute.return_value.fetchall.return_value[0]
    row.update(change)
    with pytest.raises(HistoricalSafetyError, match=error):
        _validate_sources(connection, req)


def test_normalized_future_revision_is_not_silently_filtered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    req = request()
    connection = connection_for(monkeypatch, req)
    connection.execute.return_value.fetchone.return_value["violations"] = 1
    with pytest.raises(HistoricalSafetyError, match="future source revision"):
        _validate_sources(connection, req)


def test_operational_context_cannot_be_relabelled_as_reconstruction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    req = request()
    connection = connection_for(monkeypatch, req)
    module.SourceRepository(connection).read_context.return_value["knowledge_mode"] = (
        "OPERATIONAL_REPLAY"
    )
    with pytest.raises(HistoricalSafetyError, match="context mismatch"):
        _validate_sources(connection, req)


def test_isolation_inserts_new_context_without_touching_original_or_weekly_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    req = request()
    connection = connection_for(monkeypatch, req)
    database = MagicMock()
    database.connect.return_value.__enter__.return_value = connection
    context = _isolated_context(database, req)
    assert context.execution_context_id != req.execution_context_id
    assert context.cutoff_at == req.training_cutoff
    inserts = [
        call for call in connection.execute.call_args_list
        if "INSERT INTO" in call.args[0]
    ]
    assert len(inserts) == 1
    assert inserts[0].args[1][1:3] == (req.input_manifest_id, req.training_cutoff)
    sql = " ".join(call.args[0].lower() for call in connection.execute.call_args_list)
    assert all(name not in sql for name in (
        "update ", "delete ", "active_model_assignment", "weekly_training_run", "champion",
    ))


def prepared() -> PreparedTrainingData:
    index = pd.MultiIndex.from_tuples(
        [(pd.Timestamp("2026-08-01"), "IA"), (pd.Timestamp("2026-09-25"), "IA")],
        names=["datetime", "instrument"],
    )
    return PreparedTrainingData(
        pd.DataFrame({"A": [1.0, 2.0]}, index=index),
        pd.DataFrame({
            "label": [0.1, float("nan")],
            "entry_date": [pd.Timestamp("2026-08-03"), pd.NaT],
            "exit_date": [pd.Timestamp("2026-08-28"), pd.NaT],
        }, index=index),
        pd.Series([1.0, 2.0], index=index), pd.DataFrame(), ("A",),
    )


def test_inference_anchor_does_not_need_a_forward_label() -> None:
    validate_reconstruction_data(
        prepared(), HistoricalTrainingFence(date(2026, 9, 25), CUTOFF),
    )


def test_future_training_label_is_rejected_before_fitting() -> None:
    data = prepared()
    data.labels.iloc[0, data.labels.columns.get_loc("exit_date")] = pd.Timestamp("2026-09-28")
    with pytest.raises(HistoricalSafetyError, match="not matured"):
        validate_reconstruction_data(data, HistoricalTrainingFence(date(2026, 9, 25), CUTOFF))


def test_future_feature_or_evaluation_row_is_rejected() -> None:
    data = prepared()
    data.features.index = pd.MultiIndex.from_tuples([
        (pd.Timestamp("2026-08-01"), "IA"), (pd.Timestamp("2026-09-28"), "IA"),
    ], names=["datetime", "instrument"])
    with pytest.raises(HistoricalSafetyError, match="data exceeds"):
        validate_reconstruction_data(data, HistoricalTrainingFence(date(2026, 9, 25), CUTOFF))


def setup_service(
    monkeypatch: pytest.MonkeyPatch, metrics: dict[str, object],
) -> tuple[ReconstructionRequest, MagicMock]:
    req = request()
    context_id, export_id, model_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    connection = connection_for(monkeypatch, req)
    database = MagicMock()
    database.connect.return_value.__enter__.return_value = connection
    monkeypatch.setattr(module, "version", lambda _: "test")

    def export(**kwargs: object) -> SimpleNamespace:
        path = kwargs["output_root"] / str(export_id)
        path.mkdir(parents=True)
        (path / "manifest.json").write_text(json.dumps({
            "content_hash": "c" * 64,
            "execution_context_id": str(context_id), "artifacts": {},
        }), encoding="utf-8")
        return SimpleNamespace(
            export_run_id=export_id, execution_context_id=context_id,
            universe_version_id=req.universe_version_id, artifact_hash="c" * 64,
        )

    monkeypatch.setattr(module.HistoricalQlibExportService, "export", lambda _, **kw: export(**kw))
    monkeypatch.setattr(module, "_isolated_context", lambda *_: SimpleNamespace(
        execution_context_id=context_id, source_audit={
            "normalized_future_revision_count": 0,
            "snapshot_source_available_at_max": CUTOFF,
        },
    ))
    monkeypatch.setattr(module, "_validate_sources", lambda *_: {
        "normalized_future_revision_count": 0,
        "snapshot_source_available_at_max": CUTOFF,
    })
    config_root = ROOT / "config" / "analytics"
    model = load_versioned_config(config_root / "model_lightgbm_20d_v1.yaml")
    label = load_versioned_config(config_root / "label_forward_return_20d_v1.yaml")
    registered = {
        "model_name": "lightgbm", "version": str(model.payload["version"]),
        "config_hash": _canonical_hash({
            "model_config_hash": model.config_hash, "label_config_hash": label.config_hash,
        }),
        "processor_version_id": None, "label_semantics": "RAW_STOCK_20D_RETURN",
        "model_purpose": "MEDIUM_20D", "return_policy": "PRICE_RETURN",
        "promotion_status": "SHADOW",
        "export_run_id": export_id,
        "metrics": metrics,
        "split_spec": {
            "fit_at": datetime.now(UTC).isoformat(),
            "fit_completed_at": datetime.now(UTC).isoformat(),
            "training_cutoff": CUTOFF.isoformat(),
            "anchor_session": req.anchor_session.isoformat(),
            "promotion_allowed": False,
            "training_data_end": "2026-09-25 00:00:00",
            "training_label_exit_max": "2026-09-25 00:00:00",
            "processor_fit_data_end": "2026-08-01 00:00:00",
        },
    }

    def train(**kwargs: object) -> TrainingWorkflowSummary:
        assert kwargs["reconstruction"] == HistoricalTrainingFence(req.anchor_session, CUTOFF)
        path = kwargs["output_root"] / "experiment"
        path.mkdir(parents=True)
        weights = path / "lightgbm.txt"
        weights.write_text("test-only mock trainer weights", encoding="utf-8")
        registered["artifact_hash"] = module.sha256_file(weights)
        pd.DataFrame({f"feature::F{i}": [1.0] for i in range(158)}).to_parquet(
            path / "training_dataset.parquet",
        )
        def execute(sql, _params):
            row = registered
            if "FROM analytics.qlib_export_run" in sql:
                row = {
                    "execution_context_id": context_id, "status": "SUCCEEDED",
                    "artifact_hash": "c" * 64,
                }
            elif "FROM ops.execution_context" in sql:
                row = {
                    "input_manifest_id": req.input_manifest_id, "cutoff_at": CUTOFF,
                    "knowledge_mode": "HISTORICAL_RECONSTRUCTION",
                }
            cursor = MagicMock()
            cursor.fetchone.return_value = row
            return cursor

        connection.execute.side_effect = execute
        return TrainingWorkflowSummary(
            "experiment", path, export_id, model_id, "lightgbm",
            {"lightgbm": metrics}, "MEDIUM_20D", 20, "PRICE_RETURN", False,
        )

    monkeypatch.setattr(module, "run_training_only_workflow", train)
    return req, database


def test_reconstruction_packages_bound_artifact_but_never_promotes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    req, database = setup_service(monkeypatch, METRICS)
    artifact = reconstruct_challenger(
        database=database, settings=MagicMock(), request=req,
        repository_root=ROOT, output_root=tmp_path,
    )
    manifest = ArtifactManifest.from_bytes(
        artifact.manifest_path.read_bytes(), expected_purpose="MEDIUM_20D",
    )
    assert manifest.model_version_id == artifact.manifest.model_version_id
    proof = json.loads((artifact.manifest_path.parent / "reconstruction.json").read_text())
    assert proof["promotion_allowed"] is False
    assert proof["manifest_sha256"] == artifact.manifest_sha256
    assert datetime.fromisoformat(proof["generated_at"]) > CUTOFF
    assert datetime.fromisoformat(proof["artifact_created_at"]) > CUTOFF
    assert proof["weekly_gate_results"]["absolute.rank_ic_mean"]["passed"] is False
    assert proof["weekly_gate_results"]["absolute.rank_ic_mean"]["enforced"] is False
    assert proof["weekly_gate_results"]["absolute.coverage"]["enforced"] is True
    kwargs = {
        "manifest_path": artifact.manifest_path,
        "manifest_sha256": artifact.manifest_sha256,
        "provenance_sha256": module.sha256_file(
            artifact.manifest_path.parent / "reconstruction.json",
        ),
        "signal_session": date(2026, 10, 2),
        "knowledge_mode": "HISTORICAL_RECONSTRUCTION",
    }
    assert validate_reconstructed_artifact(**kwargs) == manifest
    with pytest.raises(HistoricalSafetyError, match="not operational"):
        validate_reconstructed_artifact(**(kwargs | {"knowledge_mode": "OPERATIONAL_REPLAY"}))
    with pytest.raises(HistoricalSafetyError, match="not bound"):
        validate_reconstructed_artifact(**(kwargs | {"signal_session": date(2026, 10, 5)}))
    with pytest.raises(HistoricalSafetyError, match="checksum"):
        validate_reconstructed_artifact(**(kwargs | {"provenance_sha256": "f" * 64}))
    sql = " ".join(
        call.args[0].lower()
        for call in database.connect.return_value.__enter__.return_value.execute.call_args_list
    )
    assert all(name not in sql for name in (
        "active_model_assignment", "weekly_training_run", "update ", "champion",
    ))
    with pytest.raises(FileExistsError):
        reconstruct_challenger(
            database=database, settings=MagicMock(), request=req,
            repository_root=ROOT, output_root=tmp_path,
        )


@pytest.mark.parametrize("changes", [
    {"coverage": 0.79}, {"test_blocks": 2}, {"rank_ic_mean": float("nan")},
])
def test_suspension_does_not_disable_integrity_gates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, changes: dict[str, object],
) -> None:
    req, database = setup_service(monkeypatch, METRICS | changes)
    with pytest.raises(HistoricalSafetyError, match="retained weekly integrity"):
        reconstruct_challenger(
            database=database, settings=MagicMock(), request=req,
            repository_root=ROOT, output_root=tmp_path,
        )
    assert (tmp_path / str(req.reconstruction_id) / "FAILED").exists()
    assert not (tmp_path / str(req.reconstruction_id) / "artifact").exists()


def test_scoped_model_requires_matching_prediction_quality_mask(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    req, database = setup_service(monkeypatch, METRICS)
    artifact = reconstruct_challenger(
        database=database, settings=MagicMock(), request=req,
        repository_root=ROOT, output_root=tmp_path,
    )
    path = artifact.manifest_path.parent / "reconstruction.json"
    proof = json.loads(path.read_text(encoding="utf-8"))
    mask = "e" * 64
    proof["split_spec"]["certified_eligibility_scope"] = {"quality_mask_sha256": mask}
    proof["source_audit"]["certified_scope"] = {"quality_mask_sha256": mask}
    path.write_text(json.dumps(proof), encoding="utf-8")
    kwargs = {
        "manifest_path": artifact.manifest_path, "manifest_sha256": artifact.manifest_sha256,
        "provenance_sha256": module.sha256_file(path), "signal_session": date(2026, 9, 30),
        "knowledge_mode": "HISTORICAL_RECONSTRUCTION",
    }
    with pytest.raises(HistoricalSafetyError, match="quality scopes differ"):
        validate_reconstructed_artifact(**kwargs)
    with pytest.raises(HistoricalSafetyError, match="quality scopes differ"):
        validate_reconstructed_artifact(**kwargs, expected_quality_mask_sha256="f" * 64)
    assert validate_reconstructed_artifact(
        **kwargs, expected_quality_mask_sha256=mask,
    ).model_version_id == artifact.manifest.model_version_id


@pytest.mark.parametrize("future", [False, True])
def test_rich_context_can_be_frozen_from_explicit_existing_snapshots_only(
    monkeypatch: pytest.MonkeyPatch, future: bool,
) -> None:
    req = request()
    member = ManifestSnapshot(
        uuid.uuid4(), "massive_grouped_daily_backfill", "FULL", "SINGLE", 0, None,
        date(2024, 9, 25), req.anchor_session,
    )
    connection = MagicMock()
    connection.execute.return_value.fetchall.return_value = [{
        "source_snapshot_id": member.source_snapshot_id, "dataset_code": member.dataset_code,
        "snapshot_kind": member.snapshot_kind, "parent_snapshot_id": member.parent_snapshot_id,
        "coverage_start": member.coverage_start, "coverage_end": member.coverage_end,
        "source_available_at": CUTOFF + timedelta(seconds=1) if future else CUTOFF,
    }]
    database = MagicMock()
    database.connect.return_value.__enter__.return_value = connection
    audit = MagicMock()
    monkeypatch.setattr(context_module, "_validate_sources", audit)
    kwargs = {
        "database": database, "reconstruction_id": req.reconstruction_id,
        "signal_session": req.signal_session, "anchor_session": req.anchor_session,
        "training_cutoff": req.training_cutoff, "universe_version_id": req.universe_version_id,
        "members": (member,),
    }
    if future:
        with pytest.raises(HistoricalSafetyError, match="cutoff mismatch"):
            context_module.freeze_training_context(**kwargs)
        assert len(connection.execute.call_args_list) == 1
        audit.assert_not_called()
    else:
        frozen = context_module.freeze_training_context(**kwargs)
        assert frozen.execution_context_id != req.execution_context_id
        audit.assert_called_once_with(connection, frozen)
        sql = " ".join(call.args[0].lower() for call in connection.execute.call_args_list)
        assert all(name not in sql for name in (
            "update ", "delete ", "active_model_assignment", "weekly_training_run",
        ))
        assert "insert into ops.source_snapshot" not in sql
        assert "insert into market." not in sql


@pytest.mark.parametrize("certified_subset", [False, True])
def test_core_reuses_fit_and_evaluation_with_real_time_and_train_only_processors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, certified_subset: bool,
) -> None:
    anchor = date(2026, 9, 25)
    dates = pd.bdate_range(end=anchor, periods=320)
    index = pd.MultiIndex.from_product([dates, ["IA"]], names=["datetime", "instrument"])
    labels = pd.DataFrame({
        "label": [0.1] * 300 + [float("nan")] * 20,
        "entry_date": pd.Series(dates).shift(-1).to_numpy(),
        "exit_date": pd.Series(dates).shift(-20).to_numpy(),
    }, index=index)
    features = pd.DataFrame({"A": range(320)}, index=index, dtype=float)
    original_membership = {
        session: {"IA", *(f"UNSCORED{i}" for i in range(502))}
        for session in dates
    } if certified_subset else None
    data = PreparedTrainingData(
        features, labels, features["A"], pd.DataFrame(), ("A",), original_membership,
    )
    monkeypatch.setattr(workflow, "prepare_training_data", lambda **_: data)
    ridge_fits: list[pd.Index] = []
    lgb_fits: list[dict[str, object]] = []

    class MockModel:
        def __init__(self, **_: object) -> None:
            pass

        def fit(self, frame: pd.DataFrame, _: pd.Series) -> None:
            ridge_fits.append(frame.index)

        def predict(self, frame: pd.DataFrame) -> pd.Series:
            return frame["A"]

        def save(self, path: Path) -> None:
            path.write_text("mock model", encoding="utf-8")

        def save_numeric(self, path: Path, **_: object) -> None:
            path.write_text("mock numeric model", encoding="utf-8")

    def mock_train(**kwargs: object) -> MockModel:
        lgb_fits.append(kwargs)
        return MockModel()

    @dataclass
    class MockMetrics:
        observations: int = 1
        rank_ic_mean: float = 0.1
        coverage: float = 0.9
        net_top_10_return: float = -0.1
        max_drawdown_top_10: float = -0.4

    def mock_metrics(predictions: pd.Series, *args: object, **kwargs: object) -> MockMetrics:
        del args, kwargs
        return MockMetrics(observations=len(predictions))

    monkeypatch.setattr(workflow, "RidgeBaseline", MockModel)
    monkeypatch.setattr(workflow, "train_qlib_lightgbm", mock_train)
    monkeypatch.setattr(workflow, "evaluate_predictions", mock_metrics)
    export_dir = tmp_path / "export"
    export_dir.mkdir()
    (export_dir / "manifest.json").write_text(json.dumps({
        "cutoff_at": CUTOFF.isoformat(), "export_run_id": str(uuid.uuid4()),
        "calendar_end": anchor.isoformat(), "content_hash": "c" * 64,
        "execution_context_id": str(uuid.uuid4()),
    }), encoding="utf-8")
    database = MagicMock()
    connection = database.connect.return_value.__enter__.return_value
    connection.execute.return_value.fetchone.return_value = {
        "execution_context_id": uuid.uuid4(), "universe_version_id": uuid.uuid4(),
        "end_date": anchor, "cutoff_at": CUTOFF,
    }
    monkeypatch.setattr(workflow, "Database", lambda _: database)
    registry = MagicMock()
    registry.register.side_effect = lambda _: uuid.uuid4()
    monkeypatch.setattr(workflow, "ModelRegistry", lambda _: registry)
    scope = {
        "original_reference_count": 503, "input_artifact_sha256": "d" * 64,
    } if certified_subset else None
    monkeypatch.setattr(workflow, "read_context_scope", lambda *_: scope)
    config_root = ROOT / "config" / "analytics"
    kwargs = dict(
        settings=MagicMock(), export_dir=export_dir,
        model_config=load_versioned_config(config_root / "model_lightgbm_20d_v1.yaml"),
        label_config=load_versioned_config(config_root / "label_forward_return_20d_v1.yaml"),
        output_root=tmp_path / "training",
        reconstruction=HistoricalTrainingFence(anchor, CUTOFF),
    )
    if certified_subset:
        calendar_dir = export_dir / "qlib_data" / "calendars"
        calendar_dir.mkdir(parents=True)
        (calendar_dir / "day.txt").write_text(
            "\n".join(value.date().isoformat() for value in dates), encoding="utf-8",
        )
        with pytest.raises(RuntimeError, match="coverage eligibility"):
            workflow.run_training_only_workflow(**kwargs)
        registry.register.assert_not_called()
        return
    summary = workflow.run_training_only_workflow(**kwargs)
    assert summary.model_purpose == "MEDIUM_20D"
    assert len(lgb_fits) >= 4
    final = lgb_fits[-1]
    assert ridge_fits[-1].equals(final["train_index"])
    validation_start = final["valid_index"].get_level_values("datetime").min()
    assert labels.loc[final["train_index"], "exit_date"].max() < validation_start
    assert len(registry.register.call_args_list) == 3
    for call in registry.register.call_args_list:
        registration = call.args[0]
        assert registration.promotion_status == "SHADOW"
        split = registration.split_spec
        assert datetime.fromisoformat(split["fit_at"]) > CUTOFF
        assert datetime.fromisoformat(split["fit_completed_at"]) > CUTOFF
        assert split["training_cutoff"] == CUTOFF.isoformat()
        assert split["promotion_allowed"] is False
        assert all("fit_at" not in fold for fold in split["folds"])


def test_historical_delta_cannot_hide_a_late_raw_split_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    req = request()
    parent_id = uuid.uuid4()
    parent = ManifestSnapshot(
        parent_id, "massive_splits_backfill", "FULL", "SINGLE", 0, None,
        date(2024, 10, 11), date(2025, 10, 8),
    )
    child = ManifestSnapshot(
        uuid.uuid4(), "massive_splits_backfill_derived", "DELTA", "DELTA", 0,
        parent_id, req.anchor_session, req.anchor_session,
    )
    connection = MagicMock()
    connection.execute.return_value.fetchall.return_value = [
        {
            "source_snapshot_id": member.source_snapshot_id,
            "dataset_code": member.dataset_code, "snapshot_kind": member.snapshot_kind,
            "parent_snapshot_id": member.parent_snapshot_id,
            "coverage_start": member.coverage_start, "coverage_end": member.coverage_end,
            "source_available_at": datetime(2026, 10, 10, tzinfo=UTC)
            if member is parent else CUTOFF,
        }
        for member in (parent, child)
    ]
    database = MagicMock()
    database.connect.return_value.__enter__.return_value = connection
    audit = MagicMock()
    monkeypatch.setattr(context_module, "_validate_sources", audit)
    with pytest.raises(HistoricalSafetyError, match="cutoff mismatch"):
        context_module.freeze_training_context(
            database=database, reconstruction_id=req.reconstruction_id,
            signal_session=req.signal_session, anchor_session=req.anchor_session,
            training_cutoff=req.training_cutoff, universe_version_id=req.universe_version_id,
            members=(parent, child),
        )
    assert len(connection.execute.call_args_list) == 1
    assert "SELECT" in connection.execute.call_args.args[0]
    audit.assert_not_called()
