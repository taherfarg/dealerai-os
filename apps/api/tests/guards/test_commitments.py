"""What a draft may not promise, in the three languages it writes."""

from __future__ import annotations

import pytest

from dealerai.guards import commitments


@pytest.mark.parametrize(
    "text,code",
    [
        ("I can give you a 5% discount on that one.", "discount"),
        ("Let me check with our manager for any possible discounts.", "discount"),
        ("في خصومات على الهايلكس هالشهر", "discount"),
        ("Nous avons des remises ce mois-ci.", "discount"),
        ("سعر خاص لك اليوم", "discount"),
        ("Je peux vous faire une remise.", "discount"),
        ("I will check with my manager if we can match your offer.", "discount"),
        ("I'll ask my manager about matching the price you were offered.", "discount"),
        ("راح نشوف إذا نقدر نطابق السعر", "discount"),
        ("Nous pouvons aligner notre prix.", "discount"),
        ("AED 235,000 is the final price.", "final_price"),
        ("آخر سعر 235,000 درهم", "final_price"),
        ("Delivery by Thursday, guaranteed.", "delivery"),
        ("التسليم خلال ثلاثة أيام", "delivery"),
        ("Good news — you are approved for finance.", "finance"),
        ("التمويل مضمون", "finance"),
        ("We will give you 45,000 for your Corolla.", "trade_in"),
        ("Just checking in!", "empty_followup"),
        ("أطمئن عليك", "empty_followup"),
        ("Je reviens vers vous.", "empty_followup"),
    ],
)
def test_the_promises_only_a_person_may_make(text: str, code: str) -> None:
    caught = {finding.detail for finding in commitments.check(text)}
    assert caught & set(commitments.PHRASES[code][1]), f"{text!r} did not trip {code}"


def test_a_reply_may_say_it_will_come_back_to_them() -> None:
    """An inbox reply answers what they just wrote, so it cannot be an empty
    follow-up — "je reviens vers vous" there is the holding line itself. The
    other promises still count."""
    holding = "Je vérifie l'autonomie et je reviens vers vous aujourd'hui."
    assert commitments.check(holding)  # as a follow-up, it is the empty opener
    assert commitments.check(holding, replying=True) == []
    assert commitments.check("Je peux vous faire une remise.", replying=True) != []


def test_a_reply_that_promises_nothing_passes() -> None:
    text = (
        "The 2023 Land Cruiser 4.0 is available at AED 235,000. "
        "Would you like to see it on Saturday at 11:00?"
    )
    assert commitments.check(text) == []


def test_calling_someone_is_not_valuing_their_car() -> None:
    """'We will give you a call' is the phrase without the figure that makes it
    a promise. Blocking it is how a guard gets switched off."""
    assert commitments.check("We will give you a call tomorrow.") == []
    assert commitments.check("We will give you 40,000 for it.") != []


def test_a_figure_three_clauses_away_is_not_the_valuation() -> None:
    far = "We will give you a call. " + ("Kind regards. " * 8) + "The Hilux is AED 165,000."
    assert commitments.check(far) == []


def test_one_finding_per_promise_not_per_phrase() -> None:
    """Two ways of saying discount is one thing to fix."""
    assert len(commitments.check("A discount — 10% off, today only.")) == 1


def test_two_different_promises_are_two_findings() -> None:
    findings = commitments.check("A 5% discount, and delivery by Thursday.")
    assert len(findings) == 2


def test_arabic_numerals_do_not_hide_a_valuation() -> None:
    """The guard reads ٤٥٬٠٠٠ as a figure, because the customer does."""
    assert commitments.check("سنعطيك مقابل سيارتك ٤٥٬٠٠٠") != []


def test_an_arabic_promise_inside_a_longer_word_is_still_caught() -> None:
    """Arabic prefixes attach directly, so the match is a substring one — over-
    flagging Arabic beats missing it."""
    assert commitments.check("والتسليم خلال يومين") != []


def test_the_finding_names_the_phrase_so_a_retry_can_fix_it() -> None:
    finding = commitments.check("I can give you a discount.")[0]
    assert finding.guard == "commitments"
    assert finding.detail == "discount"
    assert "only a person may do" in finding.message
