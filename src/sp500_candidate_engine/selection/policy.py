from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass

from sp500_candidate_engine.analytics.scoring import DailyScore


class SelectionShortfallError(ValueError):
    """Raised when hard gates leave fewer than the minimum candidates."""


@dataclass(frozen=True)
class SelectionPolicy:
    minimum_candidates: int = 5
    maximum_candidates: int = 10
    sector_cap: int = 2
    relaxed_sector_cap: int = 3

    def __post_init__(self) -> None:
        if not 1 <= self.minimum_candidates <= self.maximum_candidates:
            raise ValueError("Candidate bounds are invalid")
        if not 1 <= self.sector_cap <= self.relaxed_sector_cap:
            raise ValueError("Sector caps are invalid")


@dataclass(frozen=True)
class CandidateMetadata:
    instrument_id: uuid.UUID
    issuer_id: uuid.UUID
    symbol: str
    sector: str | None


@dataclass(frozen=True)
class SelectedCandidate:
    instrument_id: uuid.UUID
    issuer_id: uuid.UUID
    symbol: str
    sector: str | None
    position: int
    score: float
    rank_overall: int
    score_percentile: float
    rank_sector: int | None
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class SelectionResult:
    status: str
    candidates: tuple[SelectedCandidate, ...]
    soft_constraints_relaxed: tuple[str, ...]


def select_candidates(
    *,
    scores: tuple[DailyScore, ...],
    metadata: dict[uuid.UUID, CandidateMetadata],
    policy: SelectionPolicy,
) -> SelectionResult:
    eligible = [
        score
        for score in scores
        if score.quality_status == "OK" and score.instrument_id in metadata
    ]
    if len(eligible) < policy.minimum_candidates:
        raise SelectionShortfallError(
            f"Only {len(eligible)} hard-gate candidates remain"
        )
    ordered = sorted(
        eligible,
        key=lambda item: (-item.score, item.instrument_id.hex),
    )

    selected_ids: set[uuid.UUID] = set()
    selected_issuers: set[uuid.UUID] = set()
    sector_counts: Counter[str] = Counter()
    selected: list[tuple[DailyScore, CandidateMetadata, bool]] = []

    def fill(sector_cap: int, *, relaxed: bool) -> None:
        for score in ordered:
            if len(selected) >= policy.maximum_candidates:
                return
            item = metadata[score.instrument_id]
            if item.instrument_id in selected_ids or item.issuer_id in selected_issuers:
                continue
            sector_key = item.sector or "UNCLASSIFIED"
            if sector_counts[sector_key] >= sector_cap:
                continue
            selected_ids.add(item.instrument_id)
            selected_issuers.add(item.issuer_id)
            sector_counts[sector_key] += 1
            selected.append((score, item, relaxed))

    fill(policy.sector_cap, relaxed=False)
    relaxed_constraints: tuple[str, ...] = ()
    if len(selected) < policy.minimum_candidates:
        fill(policy.relaxed_sector_cap, relaxed=True)
        relaxed_constraints = ("sector_cap",)
    if len(selected) < policy.minimum_candidates:
        raise SelectionShortfallError(
            f"Only {len(selected)} candidates remain after allowed soft relaxation"
        )

    candidates = tuple(
        SelectedCandidate(
            instrument_id=item.instrument_id,
            issuer_id=item.issuer_id,
            symbol=item.symbol,
            sector=item.sector,
            position=position,
            score=score.score,
            rank_overall=score.rank_overall,
            score_percentile=score.score_percentile,
            rank_sector=score.rank_sector,
            reason_codes=(
                "MODEL_TOP_RANK",
                "MODEL_TOP_PERCENTILE",
                *(("SECTOR_CAP_RELAXED",) if relaxed else ()),
            ),
        )
        for position, (score, item, relaxed) in enumerate(selected, start=1)
    )
    return SelectionResult(
        status="SUCCEEDED",
        candidates=candidates,
        soft_constraints_relaxed=relaxed_constraints,
    )
