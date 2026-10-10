import uuid
from datetime import date

import pytest

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
