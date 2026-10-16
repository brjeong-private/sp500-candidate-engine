from pathlib import Path
from unittest.mock import sentinel

import pandas as pd
import pytest

from sp500_candidate_engine.analytics import phase45_workflow
from sp500_candidate_engine.analytics.phase45_workflow import (
    TrainingWorkflowSummary,
    _segment_index,
)


def test_segment_index_excludes_labels_not_mature_at_fit_time() -> None:
    index = pd.MultiIndex.from_tuples(
        [
            (pd.Timestamp("2026-01-02"), "IA"),
            (pd.Timestamp("2026-01-05"), "IA"),
        ],
        names=["datetime", "instrument"],
    )
    labels = pd.DataFrame(
        {
            "label": [0.1, 0.2],
            "exit_date": [
                pd.Timestamp("2026-01-08"),
                pd.Timestamp("2026-01-12"),
            ],
        },
        index=index,
    )

    selected = _segment_index(
        labels,
        start=pd.Timestamp("2026-01-01"),
        end=pd.Timestamp("2026-01-12"),
        fit_at=pd.Timestamp("2026-01-09"),
    )

    assert selected.tolist() == [(pd.Timestamp("2026-01-02"), "IA")]


def test_training_only_workflow_disables_score_and_selection_persistence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = TrainingWorkflowSummary(
        experiment_key="experiment",
        experiment_dir=Path("experiment"),
        export_run_id=sentinel.export_run_id,
        model_version_id=sentinel.model_version_id,
        selected_shadow_model="lightgbm",
        metrics={},
        model_purpose="SHORT_5D",
        prediction_horizon_sessions=5,
        return_policy="PRICE_RETURN",
        scorecard_quality_gate_passed=True,
    )
    captured: dict[str, object] = {}

    def run_core(**kwargs: object) -> TrainingWorkflowSummary:
        captured.update(kwargs)
        return expected

    monkeypatch.setattr(phase45_workflow, "_run_phase45_workflow", run_core)

    result = phase45_workflow.run_training_only_workflow(
        settings=sentinel.settings,
        export_dir=Path("export"),
        model_config=sentinel.model_config,
        label_config=sentinel.label_config,
        output_root=Path("output"),
    )

    assert result is expected
    assert captured["selection_config"] is None
    assert captured["persist_selection"] is False


def test_workflow_rejects_inconsistent_selection_persistence_contract() -> None:
    with pytest.raises(ValueError, match="required exactly"):
        phase45_workflow._run_phase45_workflow(
            settings=sentinel.settings,
            export_dir=Path("export"),
            model_config=sentinel.model_config,
            label_config=sentinel.label_config,
            selection_config=None,
            output_root=Path("output"),
            persist_selection=True,
        )
