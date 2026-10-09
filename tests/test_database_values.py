from decimal import Decimal

from sp500_candidate_engine.database import _price
from sp500_candidate_engine.production_repository import resolve_revision


def test_price_matches_postgresql_numeric_precision() -> None:
    assert _price(163.02000427246094) == Decimal("163.02000427")


def test_price_preserves_none() -> None:
    assert _price(None) is None


def test_same_payload_does_not_create_duplicate_revision() -> None:
    assert resolve_revision(
        current_revision=3,
        current_hash="same",
        new_hash="same",
    ) == (3, False)


def test_changed_payload_creates_next_revision() -> None:
    assert resolve_revision(
        current_revision=3,
        current_hash="old",
        new_hash="new",
    ) == (4, True)
