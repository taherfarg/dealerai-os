from __future__ import annotations

import pytest

from dealerai.guards.brand import BrandRules, check

VAT = "Prices include VAT."


def test_ordinary_copy_passes() -> None:
    assert check("The 2023 Land Cruiser has arrived. Visit us in Al Quoz.") == []


@pytest.mark.parametrize(
    "claim", ["best price", "cheapest", "guaranteed", "#1", "unbeatable", "أرخص"]
)
def test_an_unsupportable_claim_is_blocked_by_default(claim: str) -> None:
    """Comparative advertising is a legal problem in every Gulf market, and it
    is the first phrase a model reaches for when told to sound confident."""
    findings = check(f"We have the {claim} in Dubai")
    assert [f.detail for f in findings] == [claim]


def test_a_dealer_may_allow_a_claim_they_can_substantiate() -> None:
    rules = BrandRules(allow_unsupportable_claims=True)
    assert check("Guaranteed best price", rules) == []


def test_a_forbidden_word_is_blocked() -> None:
    findings = check("A bargain motor", BrandRules(forbidden_words=("bargain",)))
    assert findings[0].detail == "bargain"


def test_a_forbidden_word_inside_a_longer_word_is_not_a_match() -> None:
    """Otherwise "used" forbids "unused" and the dealer turns the guard off."""
    assert check("An unused demo car", BrandRules(forbidden_words=("used",))) == []


def test_an_arabic_forbidden_word_matches_inside_a_word() -> None:
    """Arabic prefixes attach directly, so word boundaries do not exist to match
    on. Over-flagging Arabic beats missing it."""
    assert check("والرخيص جدا", BrandRules(forbidden_words=("رخيص",))) != []


def test_a_missing_disclaimer_is_blocked() -> None:
    rules = BrandRules(required_disclaimer=VAT)
    assert check("Great car, great price.", rules)[0].detail == VAT
    assert check(f"Great car. {VAT}", rules) == []


def test_copy_with_no_approved_cta_is_blocked() -> None:
    rules = BrandRules(allowed_ctas=("Visit us", "DM to book"))
    assert check("Beautiful car.", rules) != []
    assert check("Beautiful car. DM to book a viewing.", rules) == []


def test_no_configured_ctas_means_the_check_does_not_run() -> None:
    """Empty means the dealer has no preference yet, not that the guard should
    invent one."""
    assert check("Beautiful car.", BrandRules()) == []


def test_too_many_hashtags_is_blocked_and_names_the_extras() -> None:
    text = " ".join(f"#tag{i}" for i in range(10))
    findings = check(text, BrandRules(max_hashtags=8))
    assert "10 hashtags" in findings[0].message
    assert findings[0].detail == "#tag8 #tag9"


def test_exactly_the_limit_is_fine() -> None:
    assert check(" ".join(f"#tag{i}" for i in range(8)), BrandRules(max_hashtags=8)) == []


def test_a_banned_emoji_is_blocked() -> None:
    assert check("Hot deal 🔥", BrandRules(banned_emoji=("🔥",)))[0].detail == "🔥"


def test_every_violation_is_reported_not_just_the_first() -> None:
    """An agent retrying needs the whole list. Fixing one thing at a time is
    three model calls where one would do."""
    rules = BrandRules(required_disclaimer=VAT, forbidden_words=("bargain",))
    findings = check("The cheapest bargain in town", rules)
    assert {f.detail for f in findings} == {"bargain", "cheapest", VAT}


def test_a_configured_emoji_that_is_absent_passes() -> None:
    assert check("A calm and tasteful caption.", BrandRules(banned_emoji=("🔥",))) == []
