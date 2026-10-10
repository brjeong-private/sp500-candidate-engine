from __future__ import annotations

import math
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class DailyScore:
    instrument_id: uuid.UUID
    session_date: date
    score: float
    rank_overall: int
    score_percentile: float
    rank_sector: int | None
    quality_status: str


def rank_daily_scores(
    *,
    session_date: date,
    raw_scores: dict[uuid.UUID, float],
    sectors: dict[uuid.UUID, str | None],
) -> tuple[DailyScore, ...]:
    invalid = [
        instrument_id
        for instrument_id, score in raw_scores.items()
        if not math.isfinite(score)
    ]
    if invalid:
        raise ValueError(f"Scores must be finite: {invalid}")
    ordered = sorted(raw_scores.items(), key=lambda item: (-item[1], item[0].hex))
    count = len(ordered)
    sector_positions: dict[str, int] = defaultdict(int)
    result: list[DailyScore] = []
    for overall_index, (instrument_id, score) in enumerate(ordered, start=1):
        sector = sectors.get(instrument_id)
        sector_rank = None
        if sector:
            sector_positions[sector] += 1
            sector_rank = sector_positions[sector]
        result.append(
            DailyScore(
                instrument_id=instrument_id,
                session_date=session_date,
                score=score,
                rank_overall=overall_index,
                score_percentile=(count - overall_index + 1) / count if count else 0,
                rank_sector=sector_rank,
                quality_status="OK",
            )
        )
    return tuple(result)
