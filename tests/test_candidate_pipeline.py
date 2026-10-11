import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from sp500_candidate_engine import candidate_pipeline
from sp500_candidate_engine.candidate_pipeline import find_export_for_date
from sp500_candidate_engine.cli import build_parser


def test_find_export_requires_explicit_matching_date(tmp_path) -> None:
    export = tmp_path / "run"
    export.mkdir()
    (export / "manifest.json").write_text(
        json.dumps(
            {
                "calendar_end": "2026-10-09",
                "cutoff_at": "2026-10-09T21:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    assert find_export_for_date(tmp_path, date(2026, 10, 9)) == export
    with pytest.raises(FileNotFoundError):
        find_export_for_date(tmp_path, date(2026, 10, 8))


def test_find_export_never_chooses_a_future_cutoff(tmp_path) -> None:
    for name, cutoff in (
        ("as-of-close", "2026-10-09T21:00:00+00:00"),
        ("future-revision", "2026-10-11T01:00:00+00:00"),
    ):
        export = tmp_path / name
        export.mkdir()
        (export / "manifest.json").write_text(
            json.dumps({"calendar_end": "2026-10-09", "cutoff_at": cutoff}),
            encoding="utf-8",
        )

    with pytest.raises(RuntimeError, match="decision_cutoff is required"):
        find_export_for_date(tmp_path, date(2026, 10, 9))

    selected = find_export_for_date(
        tmp_path,
        date(2026, 10, 9),
        decision_cutoff=datetime(2026, 10, 9, 21, tzinfo=UTC),
    )

    assert selected.name == "as-of-close"


def test_candidate_cli_requires_explicit_date() -> None:
    parser = build_parser()

    args = parser.parse_args(["run-candidates", "--date", "2026-10-09"])

    assert args.date == date(2026, 10, 9)


@pytest.mark.parametrize(
    (
        "horizon_sessions",
        "model_filename",
        "label_filename",
        "validation_sessions",
        "test_sessions",
        "step_sessions",
    ),
    [
        (5, "model_lightgbm_v2.yaml", "label_forward_return_5d_v2.yaml", 30, 30, 30),
        (
            20,
            "model_lightgbm_20d_v1.yaml",
            "label_forward_return_20d_v1.yaml",
            40,
            40,
            20,
        ),
    ],
)
def test_candidate_pipeline_selects_versioned_configs_by_horizon(
    tmp_path,
    monkeypatch,
    horizon_sessions: int,
    model_filename: str,
    label_filename: str,
    validation_sessions: int,
    test_sessions: int,
    step_sessions: int,
) -> None:
    monkeypatch.setattr(
        candidate_pipeline,
        "find_export_for_date",
        lambda *args, **kwargs: tmp_path,
    )
    monkeypatch.setattr(candidate_pipeline, "run_phase45_workflow", lambda **kwargs: kwargs)

    result = candidate_pipeline.run_candidate_date(
        object(),
        target_date=date(2026, 10, 9),
        repository_root=Path(__file__).parents[1],
        horizon_sessions=horizon_sessions,
    )

    assert result["model_config"].path.name == model_filename
    assert result["label_config"].path.name == label_filename
    assert result["label_config"].payload["horizon_sessions"] == horizon_sessions
    assert (
        result["model_config"].payload["prediction_semantics"]
        == f"PREDICTED_{horizon_sessions}D_RETURN"
    )
    walk_forward = result["model_config"].payload["walk_forward"]
    assert walk_forward["minimum_train_sessions"] == 100
    assert walk_forward["validation_sessions"] == validation_sessions
    assert walk_forward["test_sessions"] == test_sessions
    assert walk_forward["step_sessions"] == step_sessions
    assert walk_forward["purge_by_label_exit"] is True
    assert (
        result["model_config"].payload["evaluation"]["holding_period_sessions"]
        == horizon_sessions
    )
    if horizon_sessions == 20:
        experiment = result["model_config"].payload["experiment"]
        assert experiment == {
            "code": "E1",
            "feature_set": "ALPHA158",
            "requires_news_llm": False,
        }


def test_candidate_pipeline_rejects_unknown_horizon(tmp_path) -> None:
    with pytest.raises(ValueError, match="Unsupported candidate horizon 10"):
        candidate_pipeline.run_candidate_date(
            object(),
            target_date=date(2026, 10, 9),
            repository_root=tmp_path,
            horizon_sessions=10,
        )
