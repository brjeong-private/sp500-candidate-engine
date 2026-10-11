from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from statistics import stdev


@dataclass(frozen=True)
class PriceFeatureBar:
    instrument_id: uuid.UUID
    session_date: date
    adjusted_close: float
    raw_close: float
    raw_volume: int
    price_adjustment_status: str = "SPLIT_ADJUSTED"


@dataclass(frozen=True)
class FeatureValue:
    value: float | None
    status: str


@dataclass(frozen=True)
class LongPriceFeatureResult:
    instrument_id: uuid.UUID
    session_date: date
    values: dict[str, FeatureValue]
    available_sessions: int
    required_warmup_sessions: int = 252


def _return_series(closes: list[float]) -> list[float]:
    return [closes[index] / closes[index - 1] - 1 for index in range(1, len(closes))]


def _valid_number(value: float) -> bool:
    return math.isfinite(value) and value > 0


class LongPriceFeatureService:
    """Computes the approved P1 features from an explicit session calendar."""

    def compute(
        self,
        *,
        instrument_id: uuid.UUID,
        anchor_session: date,
        calendar: tuple[date, ...],
        stock_bars: tuple[PriceFeatureBar, ...],
        spy_bars: tuple[PriceFeatureBar, ...],
    ) -> LongPriceFeatureResult:
        if tuple(sorted(set(calendar))) != calendar:
            raise ValueError("calendar must be sorted and unique")
        try:
            anchor_index = calendar.index(anchor_session)
        except ValueError as exc:
            raise ValueError("anchor_session is not in calendar") from exc

        stock = self._index_bars(stock_bars, instrument_id)
        spy = self._index_bars(spy_bars, None)
        values: dict[str, FeatureValue] = {}

        def closes(
            source: dict[date, PriceFeatureBar], lookback: int
        ) -> list[float] | None:
            start = anchor_index - lookback
            if start < 0:
                return None
            sessions = calendar[start : anchor_index + 1]
            selected = [source.get(session) for session in sessions]
            if any(item is None for item in selected):
                return None
            result = [item.adjusted_close for item in selected if item is not None]
            return result if all(_valid_number(item) for item in result) else None

        def set_momentum(name: str, lookback: int) -> None:
            selected = closes(stock, lookback)
            values[name] = (
                FeatureValue(selected[-1] / selected[0] - 1, "OK")
                if selected is not None
                else FeatureValue(None, "INSUFFICIENT_HISTORY")
            )

        for lookback in (20, 63, 126, 252):
            set_momentum(f"momentum_{lookback}", lookback)

        selected_252 = closes(stock, 252)
        values["momentum_12m_ex_1m"] = (
            FeatureValue(selected_252[-21] / selected_252[0] - 1, "OK")
            if selected_252 is not None
            else FeatureValue(None, "INSUFFICIENT_HISTORY")
        )

        for lookback in (20, 63):
            stock_selected = closes(stock, lookback)
            spy_selected = closes(spy, lookback)
            name = f"relative_strength_spy_{lookback}"
            values[name] = (
                FeatureValue(
                    stock_selected[-1] / stock_selected[0]
                    - spy_selected[-1] / spy_selected[0],
                    "OK",
                )
                if stock_selected is not None and spy_selected is not None
                else FeatureValue(None, "UNALIGNED_BENCHMARK_HISTORY")
            )

        for lookback in (20, 63):
            selected = closes(stock, lookback)
            name = f"return_volatility_{lookback}"
            values[name] = (
                FeatureValue(stdev(_return_series(selected)) * math.sqrt(252), "OK")
                if selected is not None
                else FeatureValue(None, "INSUFFICIENT_HISTORY")
            )

        selected_63 = closes(stock, 63)
        values["downside_deviation_63"] = (
            FeatureValue(
                math.sqrt(
                    sum(min(value, 0.0) ** 2 for value in _return_series(selected_63))
                    / 63
                )
                * math.sqrt(252),
                "OK",
            )
            if selected_63 is not None
            else FeatureValue(None, "INSUFFICIENT_HISTORY")
        )

        selected_126 = closes(stock, 125)
        if selected_126 is None:
            values["max_drawdown_126"] = FeatureValue(None, "INSUFFICIENT_HISTORY")
        else:
            peak = selected_126[0]
            drawdowns: list[float] = []
            for close in selected_126:
                peak = max(peak, close)
                drawdowns.append(close / peak - 1)
            values["max_drawdown_126"] = FeatureValue(min(drawdowns), "OK")

        stock_126 = closes(stock, 126)
        spy_126 = closes(spy, 126)
        if stock_126 is None or spy_126 is None:
            values["market_beta_126"] = FeatureValue(
                None, "UNALIGNED_BENCHMARK_HISTORY"
            )
        else:
            stock_returns = _return_series(stock_126)
            spy_returns = _return_series(spy_126)
            spy_mean = sum(spy_returns) / len(spy_returns)
            stock_mean = sum(stock_returns) / len(stock_returns)
            variance = sum((value - spy_mean) ** 2 for value in spy_returns)
            if math.isclose(variance, 0.0, abs_tol=1e-18):
                values["market_beta_126"] = FeatureValue(
                    None, "ZERO_BENCHMARK_VARIANCE"
                )
            else:
                covariance = sum(
                    (stock_value - stock_mean) * (spy_value - spy_mean)
                    for stock_value, spy_value in zip(
                        stock_returns, spy_returns, strict=True
                    )
                )
                values["market_beta_126"] = FeatureValue(
                    covariance / variance, "OK"
                )

        start = anchor_index - 19
        volume_bars = (
            [stock.get(session) for session in calendar[start : anchor_index + 1]]
            if start >= 0
            else []
        )
        if len(volume_bars) != 20 or any(item is None for item in volume_bars):
            values["avg_dollar_volume_20"] = FeatureValue(
                None, "INSUFFICIENT_HISTORY"
            )
        else:
            dollar_volumes = [
                item.raw_close * item.raw_volume
                for item in volume_bars
                if item is not None
            ]
            if any(not _valid_number(value) for value in dollar_volumes):
                values["avg_dollar_volume_20"] = FeatureValue(
                    None, "INVALID_RAW_BAR"
                )
            else:
                values["avg_dollar_volume_20"] = FeatureValue(
                    sum(dollar_volumes) / 20, "OK"
                )

        return LongPriceFeatureResult(
            instrument_id=instrument_id,
            session_date=anchor_session,
            values=values,
            available_sessions=sum(
                1 for session in calendar[: anchor_index + 1] if session in stock
            ),
        )

    @staticmethod
    def _index_bars(
        bars: tuple[PriceFeatureBar, ...],
        expected_instrument: uuid.UUID | None,
    ) -> dict[date, PriceFeatureBar]:
        result: dict[date, PriceFeatureBar] = {}
        for bar in bars:
            if expected_instrument is not None and bar.instrument_id != expected_instrument:
                raise ValueError("stock_bars contains a different instrument")
            if bar.session_date in result:
                raise ValueError(f"duplicate bar for {bar.session_date}")
            if bar.price_adjustment_status != "SPLIT_ADJUSTED":
                raise ValueError(
                    "P1 requires SPLIT_ADJUSTED prices; "
                    f"got {bar.price_adjustment_status}"
                )
            result[bar.session_date] = bar
        return result


@dataclass(frozen=True)
class SecFact:
    fact_id: uuid.UUID
    filing_id: uuid.UUID
    accession_no: str
    accepted_at: datetime
    concept: str
    unit: str
    period_end: date
    context_hash: str
    value: float
    source_available_at: datetime
    observed_at: datetime


@dataclass(frozen=True)
class SecFundamentalFeatureResult:
    period_end: date | None
    accession_no: str | None
    values: dict[str, FeatureValue]
    p2_status: str
    blocking_reasons: tuple[str, ...]


class SecFundamentalFeatureService:
    """Computes only P2 fields safe from point-in-time instant SEC facts.

    TTM and YoY fields remain blocked until cumulative 10-Q and Q4 normalization
    lineage is available; the service deliberately does not approximate them.
    """

    CONCEPTS = {
        "assets": {"Assets"},
        "liabilities": {"Liabilities"},
        "cash": {
            "CashAndCashEquivalentsAtCarryingValue",
            "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        },
    }
    BLOCKED_FIELDS = (
        "revenue_yoy",
        "operating_margin_ttm",
        "operating_margin_change_yoy",
        "roa_ttm",
        "operating_cashflow_to_assets",
        "fcf_margin_ttm",
    )

    def compute(
        self, *, facts: tuple[SecFact, ...], cutoff_at: datetime
    ) -> SecFundamentalFeatureResult:
        eligible = [
            fact
            for fact in facts
            if fact.accepted_at <= cutoff_at
            and fact.source_available_at <= cutoff_at
            and fact.observed_at <= cutoff_at
            and fact.unit == "USD"
            and math.isfinite(fact.value)
        ]
        values = {
            name: FeatureValue(None, "NORMALIZATION_REQUIRED")
            for name in self.BLOCKED_FIELDS
        }
        if not eligible:
            values.update(
                {
                    "liabilities_to_assets": FeatureValue(None, "MISSING_SEC_FACTS"),
                    "cash_to_assets": FeatureValue(None, "MISSING_SEC_FACTS"),
                    "fundamental_age_days": FeatureValue(None, "MISSING_SEC_FACTS"),
                }
            )
            return SecFundamentalFeatureResult(
                period_end=None,
                accession_no=None,
                values=values,
                p2_status="BLOCKED",
                blocking_reasons=("NO_POINT_IN_TIME_SEC_FACTS", "TTM_NORMALIZATION_REQUIRED"),
            )

        latest = max(eligible, key=lambda fact: (fact.period_end, fact.accepted_at))
        # The current fact schema hashes concept into context_hash and does not retain
        # SEC dimension members. Cross-concept ratios therefore cannot prove that
        # numerator and denominator have the same dimensional context.
        values["liabilities_to_assets"] = FeatureValue(
            None, "CONTEXT_DIMENSIONS_UNAVAILABLE"
        )
        values["cash_to_assets"] = FeatureValue(
            None, "CONTEXT_DIMENSIONS_UNAVAILABLE"
        )
        values["fundamental_age_days"] = FeatureValue(
            float((cutoff_at.date() - latest.accepted_at.date()).days), "OK"
        )
        return SecFundamentalFeatureResult(
            period_end=latest.period_end,
            accession_no=latest.accession_no,
            values=values,
            p2_status="BLOCKED",
            blocking_reasons=(
                "TTM_NORMALIZATION_REQUIRED",
                "SEC_CONTEXT_DIMENSIONS_UNAVAILABLE",
            ),
        )
