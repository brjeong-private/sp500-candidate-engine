import uuid
from datetime import UTC, date, datetime, timedelta

import pytest

from sp500_candidate_engine.analytics.advanced_features import (
    LongPriceFeatureService,
    PriceFeatureBar,
    SecFact,
    SecFundamentalFeatureService,
)


def _bars(
    instrument_id: uuid.UUID,
    calendar: tuple[date, ...],
    *,
    growth: float,
) -> tuple[PriceFeatureBar, ...]:
    return tuple(
        PriceFeatureBar(
            instrument_id=instrument_id,
            session_date=session,
            adjusted_close=100 * (1 + growth) ** index,
            raw_close=100 * (1 + growth) ** index,
            raw_volume=1_000,
        )
        for index, session in enumerate(calendar)
    )


def test_long_price_features_use_exact_calendar_history() -> None:
    instrument_id = uuid.uuid4()
    spy_id = uuid.uuid4()
    start = date(2025, 1, 1)
    calendar = tuple(start + timedelta(days=index) for index in range(253))

    result = LongPriceFeatureService().compute(
        instrument_id=instrument_id,
        anchor_session=calendar[-1],
        calendar=calendar,
        stock_bars=_bars(instrument_id, calendar, growth=0.01),
        spy_bars=_bars(spy_id, calendar, growth=0.005),
    )

    assert result.values["momentum_20"].value == pytest.approx(1.01**20 - 1)
    assert result.values["relative_strength_spy_20"].value == pytest.approx(
        1.01**20 - 1.005**20
    )
    assert result.values["avg_dollar_volume_20"].status == "OK"
    assert result.available_sessions == 253


def test_long_price_features_do_not_shift_missing_spy_session() -> None:
    instrument_id = uuid.uuid4()
    spy_id = uuid.uuid4()
    start = date(2025, 1, 1)
    calendar = tuple(start + timedelta(days=index) for index in range(253))
    spy = tuple(
        bar for bar in _bars(spy_id, calendar, growth=0.005)
        if bar.session_date != calendar[-5]
    )

    result = LongPriceFeatureService().compute(
        instrument_id=instrument_id,
        anchor_session=calendar[-1],
        calendar=calendar,
        stock_bars=_bars(instrument_id, calendar, growth=0.01),
        spy_bars=spy,
    )

    assert result.values["relative_strength_spy_20"].value is None
    assert (
        result.values["relative_strength_spy_20"].status
        == "UNALIGNED_BENCHMARK_HISTORY"
    )


def test_long_price_features_reject_non_split_adjusted_input() -> None:
    instrument_id = uuid.uuid4()
    spy_id = uuid.uuid4()
    start = date(2025, 1, 1)
    calendar = tuple(start + timedelta(days=index) for index in range(253))
    stock = list(_bars(instrument_id, calendar, growth=0.01))
    stock[-1] = PriceFeatureBar(
        instrument_id=instrument_id,
        session_date=calendar[-1],
        adjusted_close=stock[-1].adjusted_close,
        raw_close=stock[-1].raw_close,
        raw_volume=stock[-1].raw_volume,
        price_adjustment_status="TOTAL_RETURN_ADJUSTED",
    )

    with pytest.raises(ValueError, match="SPLIT_ADJUSTED"):
        LongPriceFeatureService().compute(
            instrument_id=instrument_id,
            anchor_session=calendar[-1],
            calendar=calendar,
            stock_bars=tuple(stock),
            spy_bars=_bars(spy_id, calendar, growth=0.005),
        )


def test_sec_service_exposes_age_but_blocks_unsafe_cross_context_ratios() -> None:
    filing_id = uuid.uuid4()
    accepted_at = datetime(2026, 1, 10, tzinfo=UTC)
    facts = tuple(
        SecFact(
            fact_id=uuid.uuid4(),
            filing_id=filing_id,
            accession_no="0001",
            accepted_at=accepted_at,
            concept=concept,
            unit="USD",
            period_end=date(2025, 12, 31),
            context_hash=f"context-{concept}",
            value=value,
            source_available_at=accepted_at,
            observed_at=accepted_at,
        )
        for concept, value in (
            ("Assets", 100.0),
            ("Liabilities", 40.0),
            ("CashAndCashEquivalentsAtCarryingValue", 20.0),
        )
    )

    result = SecFundamentalFeatureService().compute(
        facts=facts,
        cutoff_at=datetime(2026, 1, 20, tzinfo=UTC),
    )

    assert result.values["fundamental_age_days"].value == 10
    assert result.values["liabilities_to_assets"].value is None
    assert (
        result.values["liabilities_to_assets"].status
        == "CONTEXT_DIMENSIONS_UNAVAILABLE"
    )
    assert result.p2_status == "BLOCKED"
    assert "SEC_CONTEXT_DIMENSIONS_UNAVAILABLE" in result.blocking_reasons


def test_sec_service_excludes_facts_observed_after_cutoff() -> None:
    after_cutoff = datetime(2026, 1, 21, tzinfo=UTC)
    fact = SecFact(
        fact_id=uuid.uuid4(),
        filing_id=uuid.uuid4(),
        accession_no="0002",
        accepted_at=datetime(2026, 1, 10, tzinfo=UTC),
        concept="Assets",
        unit="USD",
        period_end=date(2025, 12, 31),
        context_hash="context-assets",
        value=100,
        source_available_at=datetime(2026, 1, 10, tzinfo=UTC),
        observed_at=after_cutoff,
    )

    result = SecFundamentalFeatureService().compute(
        facts=(fact,),
        cutoff_at=datetime(2026, 1, 20, tzinfo=UTC),
    )

    assert result.p2_status == "BLOCKED"
    assert "NO_POINT_IN_TIME_SEC_FACTS" in result.blocking_reasons
