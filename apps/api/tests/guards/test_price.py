"""The price guard.

The product's one zero-tolerance failure lives here, so these tests are written
from the direction of attack: what can a model write that puts a number in front
of a customer without a database row behind it?
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from dealerai.guards.price import check, figures

ALLOWED = {Decimal(66000)}


def values(text: str) -> list[Decimal]:
    return [v for v, _ in figures(text)]


# --------------------------------------------------------------------------
# the acceptance case
# --------------------------------------------------------------------------


def test_a_discounted_figure_is_rejected_and_named() -> None:
    """T3.4's acceptance. The agent rounded down to sound attractive; the
    customer arrives expecting 64,000."""
    findings = check("Yours from 64,000 this month", allowed=ALLOWED)
    assert len(findings) == 1
    assert findings[0].detail == "64,000"
    assert "64,000" in findings[0].message
    assert "66000" in findings[0].message, "the message says what would have been acceptable"


def test_the_real_price_passes() -> None:
    assert check("Available now at AED 66,000", allowed=ALLOWED) == []


def test_an_approved_offer_passes_alongside_the_list_price() -> None:
    text = "Was AED 66,000, now AED 61,500"
    assert check(text, allowed=ALLOWED) != []
    assert check(text, allowed={Decimal(66000), Decimal(61500)}) == []


# --------------------------------------------------------------------------
# what counts as a price
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "AED 66,000",
        "66,000 AED",
        "66000 AED",
        "AED 66000",
        "66,000 درهم",
        "٦٦٬٠٠٠ درهم",
        "د.إ 66,000",
        "$66,000",
        "66k AED",
    ],
)
def test_a_price_is_found_however_it_is_written(text: str) -> None:
    """Arabic numerals, an Arabic currency word, a k suffix — a figure the guard
    cannot see is a figure it cannot block."""
    assert Decimal(66000) in values(text), f"missed the price in {text!r}"


def test_a_bare_thousands_figure_is_treated_as_a_price() -> None:
    """No currency marker, but nothing else in a car caption is written 66,000.
    Erring toward flagging costs a regeneration; erring the other way costs a
    sale."""
    assert values("Yours for 66,000") == [Decimal(66000)]


@pytest.mark.parametrize(
    "text",
    [
        "2023 Land Cruiser",
        "A 1998 classic",
        "Model year 2026",
    ],
)
def test_a_model_year_is_not_a_price(text: str) -> None:
    assert values(text) == []


@pytest.mark.parametrize(
    "text",
    [
        "12,000 km on the clock",
        "Only 18000 km",
        "400 hp",
        "650 Nm of torque",
        "7 seats",
        "5 years warranty",
        "3.5 L V6",
        "0% down payment",
        "١٢٬٠٠٠ كم",
    ],
)
def test_a_measurement_is_not_a_price(text: str) -> None:
    """A guard that rejects every caption mentioning mileage gets switched off
    in a week, and then it protects nothing."""
    assert values(text) == [], f"{text!r} was read as a price"


def test_a_small_number_is_not_a_price() -> None:
    assert values("Available in 3 colours, 2 in stock") == []


def test_a_small_number_with_a_currency_is_still_a_price() -> None:
    """ "AED 500 deposit" is a claim about money, whatever its size."""
    assert values("AED 500 deposit secures it") == [Decimal(500)]


def test_both_ends_of_a_range_are_checked() -> None:
    assert values("from 60,000 to 70,000") == [Decimal(60000), Decimal(70000)]
    assert len(check("from 60,000 to 70,000", allowed=ALLOWED)) == 2


def test_a_monthly_instalment_nobody_approved_is_rejected() -> None:
    """Finance figures are not in the vehicles table, so they cannot be
    verified — which means they cannot be published."""
    findings = check("Drive it for AED 1,500 per month", allowed=ALLOWED)
    assert [f.detail for f in findings] == ["AED 1,500"]


def test_a_decimal_price_is_read_at_full_precision() -> None:
    assert values("AED 66,000.50") == [Decimal("66000.50")]


def test_text_with_no_numbers_at_all_passes() -> None:
    assert check("The one you have been waiting for.", allowed=ALLOWED) == []


def test_with_no_allowed_prices_every_figure_is_rejected() -> None:
    """The default is not "anything goes". A caller that forgot to pass the
    vehicle's price gets a rejection, not a free pass."""
    findings = check("AED 66,000")
    assert len(findings) == 1
    assert "allowed" not in findings[0].message, "there is nothing to list"


def test_a_k_suffix_inside_a_word_is_not_a_multiplier() -> None:
    assert values("15000 kilometres") == []


# --------------------------------------------------------------------------
# Arabic measurements
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "18,000 كم",
        "١٨٬٠٠٠ كم",
        "18,000 كيلومتر",
        "18,000 كيلومترًا",
        "400 حصان",
        "8 مقاعد",
        "5 سنوات",
    ],
)
def test_an_arabic_measurement_is_not_a_price(text: str) -> None:
    """Found by the live content eval: an Arabic caption saying "18,000 كيلومتر"
    was read as a price claim and blocked the whole piece. An inflected Arabic
    word has no word boundary after its stem."""
    assert values(text) == [], f"{text!r} was read as a price"


def test_an_arabic_price_is_still_a_price() -> None:
    """The control. Loosening the unit match must not stop the guard seeing a
    real figure."""
    assert values("٣١٠٬٠٠٠ درهم") == [Decimal(310000)]
    assert values("السعر 310,000 درهم") == [Decimal(310000)]
