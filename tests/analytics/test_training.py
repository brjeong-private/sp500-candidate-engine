import pandas as pd

from sp500_candidate_engine.analytics.phase45_workflow import Phase45Summary
from sp500_candidate_engine.analytics.training import FrameDataset


def test_frame_dataset_exposes_qlib_feature_label_shape() -> None:
    index = pd.MultiIndex.from_tuples(
        [
            (pd.Timestamp("2026-01-02"), "IA"),
            (pd.Timestamp("2026-01-05"), "IA"),
        ],
        names=["datetime", "instrument"],
    )
    features = pd.DataFrame({"F1": [1.0, 2.0], "F2": [3.0, 4.0]}, index=index)
    labels = pd.Series([0.1, 0.2], index=index)
    dataset = FrameDataset(
        features=features,
        labels=labels,
        segments={"train": index[:1], "valid": index[1:]},
    )

    prepared = dataset.prepare(
        "train",
        col_set=["feature", "label"],
        data_key="learn",
    )

    assert list(prepared["feature"].columns) == ["F1", "F2"]
    assert list(prepared["label"].columns) == ["LABEL0"]


def test_phase45_summary_identifies_shadow_model_semantics() -> None:
    assert "selected_shadow_model" in Phase45Summary.__dataclass_fields__
    assert "promotion_gate_passed" in Phase45Summary.__dataclass_fields__
