from __future__ import annotations

import math
import uuid
from collections import Counter
from dataclasses import asdict, dataclass
from fractions import Fraction

from sp500_candidate_engine.database import _canonical_hash


@dataclass(frozen=True)
class FusionPolicy:
    version: str = "medium-top20-rrf-v1"
    k: int = 10
    sector_cap: int = 2
    relaxed_sector_cap: int = 4
    requested_count: int = 20

    def __post_init__(self) -> None:
        if (
            any(type(value) is not int for value in (
                self.k, self.sector_cap, self.relaxed_sector_cap, self.requested_count
            ))
            or self.k <= 0
            or self.requested_count != 20
            or not 1 <= self.sector_cap <= self.relaxed_sector_cap <= 20
            or not self.version
        ):
            raise ValueError("Invalid Fusion policy")

    @property
    def config_hash(self) -> str:
        return _canonical_hash(asdict(self))


@dataclass(frozen=True)
class FusionInput:
    instrument_id: uuid.UUID
    issuer_id: uuid.UUID
    symbol: str
    sector: str | None
    position: int
    score: float
    original_rank: int
    evidence_ids: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class FusionCandidate:
    instrument_id: uuid.UUID
    issuer_id: uuid.UUID
    symbol: str
    sector: str | None
    position: int
    quant: FusionInput | None
    llm: FusionInput | None
    rrf: Fraction
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class FusionResult:
    status: str
    candidates: tuple[FusionCandidate, ...]
    audit: tuple[dict[str, object], ...]
    union_count: int
    sector_cap_relaxed: bool


def rrf_score(
    quant_rank: int | None, llm_rank: int | None, *, k: int = 10
) -> Fraction:
    if type(k) is not int or k <= 0 or (quant_rank is None and llm_rank is None):
        raise ValueError("Invalid RRF input")
    score = Fraction(0)
    for rank in (quant_rank, llm_rank):
        if rank is not None:
            if type(rank) is not int or not 1 <= rank <= 20:
                raise ValueError("RRF ranks must be integers from 1 to 20")
            score += Fraction(1, k + rank)
    return score


def _validate_source(items: tuple[FusionInput, ...], *, llm: bool) -> None:
    if (
        len(items) != 20
        or {item.position for item in items} != set(range(1, 21))
        or len({item.instrument_id for item in items}) != 20
        or len({item.issuer_id for item in items}) != 20
    ):
        raise ValueError("Fusion sources must contain 20 unique, contiguous candidates")
    for item in items:
        if (
            type(item.position) is not int
            or type(item.original_rank) is not int
            or item.original_rank < 1
            or not item.symbol
            or not math.isfinite(item.score)
            or (llm and not 0 <= item.score <= 100)
        ):
            raise ValueError("Invalid source candidate")


def fuse_candidates(
    *,
    quantitative: tuple[FusionInput, ...],
    llm: tuple[FusionInput, ...],
    gate_reasons: dict[uuid.UUID, tuple[str, ...]],
    policy: FusionPolicy | None = None,
    model_purpose: str = "MEDIUM_20D",
) -> FusionResult:
    if model_purpose != "MEDIUM_20D":
        raise ValueError("Fusion supports MEDIUM_20D only")
    policy = policy or FusionPolicy()
    _validate_source(quantitative, llm=False)
    _validate_source(llm, llm=True)
    quant_by_id = {item.instrument_id: item for item in quantitative}
    llm_by_id = {item.instrument_id: item for item in llm}
    union = quant_by_id.keys() | llm_by_id.keys()
    ranked: list[FusionCandidate] = []
    audit: list[dict[str, object]] = []
    for instrument_id in sorted(union, key=lambda value: value.hex):
        quant_item = quant_by_id.get(instrument_id)
        llm_item = llm_by_id.get(instrument_id)
        item = quant_item or llm_item
        assert item is not None
        if quant_item and llm_item and (
            quant_item.issuer_id != llm_item.issuer_id
            or quant_item.symbol != llm_item.symbol
            or quant_item.sector != llm_item.sector
        ):
            raise ValueError("Source instrument identity mismatch")
        score = rrf_score(
            quant_item.position if quant_item else None,
            llm_item.position if llm_item else None,
            k=policy.k,
        )
        reasons = gate_reasons.get(instrument_id, ("MISSING_ELIGIBILITY",))
        audit.append({
            "instrument_id": str(instrument_id),
            "issuer_id": str(item.issuer_id),
            "quant_rank": quant_item.position if quant_item else None,
            "llm_rank": llm_item.position if llm_item else None,
            "rrf_numerator": score.numerator,
            "rrf_denominator": score.denominator,
            "exclusion_reasons": list(reasons),
            "selected": False,
        })
        if not reasons:
            ranked.append(FusionCandidate(
                instrument_id, item.issuer_id, item.symbol, item.sector, 0,
                quant_item, llm_item, score,
                ("RRF_BOTH" if quant_item and llm_item else "RRF_SINGLE",),
            ))
    ranked.sort(key=lambda item: (-item.rrf, item.instrument_id.hex))
    audit_by_id = {item["instrument_id"]: item for item in audit}
    issuers: set[uuid.UUID] = set()
    eligible: list[FusionCandidate] = []
    for item in ranked:
        if item.issuer_id in issuers:
            audit_by_id[str(item.instrument_id)]["exclusion_reasons"] = ["ISSUER_DUPLICATE"]
        else:
            issuers.add(item.issuer_id)
            eligible.append(item)
    counts: Counter[str] = Counter()
    selected: dict[uuid.UUID, FusionCandidate] = {}
    relaxed = False
    for cap in (policy.sector_cap, policy.relaxed_sector_cap):
        for item in eligible:
            sector = item.sector or "UNCLASSIFIED"
            if len(selected) == 20:
                break
            if item.instrument_id in selected or counts[sector] >= cap:
                continue
            is_relaxed = cap != policy.sector_cap
            relaxed |= is_relaxed
            selected[item.instrument_id] = FusionCandidate(
                **{**item.__dict__, "reason_codes": (
                    *item.reason_codes, *(("SECTOR_CAP_RELAXED",) if is_relaxed else ())
                )}
            )
            counts[sector] += 1
        if len(selected) == 20:
            break
    final = tuple(
        FusionCandidate(**{**item.__dict__, "position": position})
        for position, item in enumerate(
            sorted(selected.values(), key=lambda item: (-item.rrf, item.instrument_id.hex)), 1
        )
    )
    for item in eligible:
        row = audit_by_id[str(item.instrument_id)]
        row["selected"] = item.instrument_id in selected
        if not row["selected"]:
            row["exclusion_reasons"] = [
                "SECTOR_CAP" if counts[item.sector or "UNCLASSIFIED"]
                >= (policy.relaxed_sector_cap if relaxed else policy.sector_cap)
                else "TARGET_FILLED"
            ]
    return FusionResult(
        "SUCCEEDED" if len(final) == 20 else "SHORTFALL",
        final, tuple(audit), len(union), relaxed,
    )
