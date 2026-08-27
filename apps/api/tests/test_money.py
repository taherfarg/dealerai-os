from __future__ import annotations

from decimal import Decimal

import pytest

from dealerai.core.money import Money


def test_minor_units_round_trip() -> None:
    m = Money(6_600_000, "AED")
    assert m.major == Decimal("66000.00")
    assert m.format() == "AED 66,000.00"


def test_from_major_accepts_str_and_decimal() -> None:
    assert Money.from_major("66000", "AED") == Money(6_600_000, "AED")
    assert Money.from_major(Decimal("1234.56"), "AED") == Money(123_456, "AED")


def test_float_is_refused_everywhere() -> None:
    with pytest.raises(TypeError):
        Money(1.5, "AED")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        Money.from_major(66000.0, "AED")  # type: ignore[arg-type]


def test_bool_is_not_an_int_here() -> None:
    with pytest.raises(TypeError):
        Money(True, "AED")  # type: ignore[arg-type]


def test_three_decimal_gulf_currencies() -> None:
    """KWD, BHD and OMR are 3-decimal. Treating them as 2 is a 10x pricing error."""
    kwd = Money.from_major("1234.567", "KWD")
    assert kwd.amount_minor == 1_234_567
    assert kwd.format() == "KWD 1,234.567"


def test_zero_decimal_currency() -> None:
    assert Money.from_major("5000", "JPY").amount_minor == 5000


def test_excess_precision_is_rejected() -> None:
    with pytest.raises(ValueError, match="precision"):
        Money.from_major("10.005", "AED")


def test_currency_is_validated_and_normalised() -> None:
    assert Money(100, "aed").currency == "AED"
    with pytest.raises(ValueError):
        Money(100, "AEDX")
