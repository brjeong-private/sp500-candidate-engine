from decimal import Decimal

from sp500_candidate_engine.database import _price


def test_price_matches_postgresql_numeric_precision() -> None:
    assert _price(163.02000427246094) == Decimal("163.02000427")


def test_price_preserves_none() -> None:
    assert _price(None) is None
