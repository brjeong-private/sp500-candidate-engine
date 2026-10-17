from dataclasses import replace
from fractions import Fraction
from uuid import UUID

import pytest

from sp500_candidate_engine.fusion.policy import (
    FusionInput,
    FusionPolicy,
    fuse_candidates,
    rrf_score,
)


def source(offset=0, issuer_offset=None, sector_count=10):
    issuer_offset = offset if issuer_offset is None else issuer_offset
    return tuple(
        FusionInput(
            UUID(int=index + offset), UUID(int=index + issuer_offset), f"T{index + offset}",
            f"S{index % sector_count}", index, 0.1, index + 100,
        )
        for index in range(1, 21)
    )


def fuse(quant, llm, gates=None, **kwargs):
    if gates is None:
        gates = {item.instrument_id: () for item in (*quant, *llm)}
    return fuse_candidates(quantitative=quant, llm=llm, gate_reasons=gates, **kwargs)


def test_exact_default_rrf_and_single_first_beats_common_last():
    assert rrf_score(1, None) == Fraction(1, 11)
    assert rrf_score(20, 20) == Fraction(1, 15)
    assert rrf_score(1, None) > rrf_score(20, 20)
    assert rrf_score(1, None, k=60) < rrf_score(20, 20, k=60)


@pytest.mark.parametrize("quant,llm,k", [
    (None, None, 10), (0, 1, 10), (-1, 2, 10), (21, 2, 10),
    (True, 2, 10), (1.0, 2, 10), (1, 2, 0), (1, 2, True),
])
def test_invalid_rrf_inputs_fail(quant, llm, k):
    with pytest.raises(ValueError):
        rrf_score(quant, llm, k=k)


def test_shared_instruments_sum_and_original_ranks_do_not_affect_rrf():
    quant = source()
    result = fuse(quant, quant)
    assert result.status == "SUCCEEDED"
    assert result.candidates[0].rrf == Fraction(2, 11)
    assert result.candidates[0].quant.original_rank == 101
    assert [item.position for item in result.candidates] == list(range(1, 21))


def test_different_share_classes_do_not_sum_or_copy_values():
    quant, llm = source(), source(100, issuer_offset=0)
    result = fuse(quant, llm)
    assert len(result.candidates) == 20
    assert all(item.rrf == Fraction(1, 10 + item.quant.position)
               for item in result.candidates)
    assert all(item.llm is None for item in result.candidates)
    assert sum(row["exclusion_reasons"] == ["ISSUER_DUPLICATE"] for row in result.audit) == 20


def test_best_share_class_failing_gate_does_not_hide_eligible_alternative():
    quant, llm = source(), source(100, issuer_offset=0)
    gates = {item.instrument_id: () for item in (*quant, *llm)}
    gates[quant[0].instrument_id] = ("BLOCKING_QUALITY_ISSUE",)
    result = fuse(quant, llm, gates)
    chosen = next(item for item in result.candidates if item.issuer_id == UUID(int=1))
    assert chosen.instrument_id == llm[0].instrument_id
    assert chosen.quant is None


def test_sector_relaxation_then_final_reranking():
    quant = source(sector_count=5)
    result = fuse(quant, quant)
    assert result.status == "SUCCEEDED"
    assert result.sector_cap_relaxed
    assert [item.rrf for item in result.candidates] == sorted(
        [item.rrf for item in result.candidates], reverse=True
    )


def test_union_shortfall_never_fills_outside_input_lists():
    quant, llm = source(sector_count=1), source(100, sector_count=1)
    result = fuse(quant, llm)
    assert result.status == "SHORTFALL"
    assert len(result.candidates) == 4
    assert result.union_count == 40


def test_missing_gate_is_fail_closed():
    result = fuse(source(), source(), {})
    assert result.status == "SHORTFALL"
    assert not result.candidates
    assert all(row["exclusion_reasons"] == ["MISSING_ELIGIBILITY"] for row in result.audit)


def test_ties_are_symmetric_and_input_order_independent():
    quant, llm = source(), source(100)
    first = fuse(quant, llm)
    second = fuse(tuple(reversed(llm)), tuple(reversed(quant)))
    assert [item.instrument_id for item in first.candidates] == [
        item.instrument_id for item in second.candidates
    ]


@pytest.mark.parametrize("invalid", [
    (), source()[:19],
    (replace(source()[0], position=2), *source()[1:]),
    (replace(source()[0], score=float("nan")), *source()[1:]),
])
def test_source_contract_is_strict(invalid):
    with pytest.raises(ValueError):
        fuse(invalid, source())


def test_short_purpose_and_invalid_policy_rejected():
    with pytest.raises(ValueError, match="MEDIUM_20D"):
        fuse(source(), source(), model_purpose="SHORT_5D")
    with pytest.raises(ValueError):
        FusionPolicy(requested_count=10)
