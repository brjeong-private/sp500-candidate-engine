import uuid
from datetime import date
from pathlib import Path

import pytest

from sp500_candidate_engine.analytics.config import load_versioned_config
from sp500_candidate_engine.analytics.scoring import DailyScore
from sp500_candidate_engine.selection.policy import (
    CandidateMetadata,
    SelectionPolicy,
    SelectionShortfallError,
    select_candidates,
)


def _score(position: int, sector: str) -> tuple[DailyScore, CandidateMetadata]:
    instrument_id = uuid.UUID(int=position)
    score = DailyScore(
        instrument_id=instrument_id,
        session_date=date(2026, 10, 8),
        score=float(20 - position),
        rank_overall=position,
        score_percentile=(21 - position) / 20,
        rank_sector=position,
        quality_status="OK",
    )
    metadata = CandidateMetadata(
        instrument_id=instrument_id,
        issuer_id=uuid.UUID(int=position),
        symbol=f"S{position}",
        sector=sector,
    )
    return score, metadata


def test_selection_scans_entire_universe_and_relaxes_only_sector_cap() -> None:
    items = [_score(index, "Tech" if index <= 8 else "Finance") for index in range(1, 13)]
    result = select_candidates(
        scores=tuple(item[0] for item in items),
        metadata={item[1].instrument_id: item[1] for item in items},
        policy=SelectionPolicy(
            minimum_candidates=5,
            maximum_candidates=10,
            sector_cap=2,
            relaxed_sector_cap=3,
        ),
    )

    assert 5 <= len(result.candidates) <= 10
    assert any("SECTOR_CAP_RELAXED" in item.reason_codes for item in result.candidates)
    assert len({item.instrument_id for item in result.candidates}) == len(result.candidates)


def test_selection_fails_closed_when_hard_gate_pool_is_too_small() -> None:
    items = [_score(index, "Tech") for index in range(1, 5)]

    with pytest.raises(SelectionShortfallError):
        select_candidates(
            scores=tuple(item[0] for item in items),
            metadata={item[1].instrument_id: item[1] for item in items},
            policy=SelectionPolicy(),
        )


def test_selection_keeps_eligible_candidates_when_all_predictions_are_negative() -> None:
    items = [_score(index, f"Sector-{index}") for index in range(1, 11)]
    negative_scores = tuple(
        DailyScore(
            instrument_id=score.instrument_id,
            session_date=score.session_date,
            score=-float(score.rank_overall) / 100,
            rank_overall=score.rank_overall,
            score_percentile=score.score_percentile,
            rank_sector=score.rank_sector,
            quality_status=score.quality_status,
        )
        for score, _ in items
    )

    result = select_candidates(
        scores=negative_scores,
        metadata={item[1].instrument_id: item[1] for item in items},
        policy=SelectionPolicy(),
    )

    assert len(result.candidates) == 10
    assert all(candidate.score < 0 for candidate in result.candidates)
    assert all(
        "NON_POSITIVE_PREDICTION" in candidate.reason_codes
        for candidate in result.candidates
    )


@pytest.mark.parametrize("count", [19, 20, 50])
def test_medium_policy_returns_exact_twenty_or_fails_closed(count) -> None:
    config = load_versioned_config(
        Path(__file__).parents[2]
        / "config" / "analytics" / "selection_medium_20d_v1.yaml"
    )
    policy = SelectionPolicy(
        **{
            key: int(config.payload[key])
            for key in (
                "minimum_candidates", "maximum_candidates",
                "sector_cap", "relaxed_sector_cap",
            )
        }
    )
    items = [_score(index, f"Sector-{index % 11}") for index in range(1, count + 1)]

    def select():
        return select_candidates(
            scores=tuple(item[0] for item in items),
            metadata={item[1].instrument_id: item[1] for item in items},
            policy=policy,
        )

    if count < 20:
        with pytest.raises(SelectionShortfallError):
            select()
    else:
        result = select()
        assert result.status == "SUCCEEDED"
        assert len(result.candidates) == 20
        assert [item.position for item in result.candidates] == list(range(1, 21))
        assert len({item.issuer_id for item in result.candidates}) == 20
