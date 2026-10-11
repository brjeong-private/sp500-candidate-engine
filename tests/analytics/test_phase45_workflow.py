import pandas as pd

from sp500_candidate_engine.analytics.phase45_workflow import _segment_index


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
