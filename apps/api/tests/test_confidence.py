"""The band, and the order it is decided in."""

from __future__ import annotations

import pytest

from dealerai.sales.confidence import band

#: Everything going right, so each test can change exactly one thing.
HIGH: dict[str, object] = {
    "intent_confidence": 0.95,
    "needs_human": None,
    "regenerated": False,
    "guards_passed_first_time": True,
    "has_sources": True,
}


def test_a_well_grounded_price_answer_is_high() -> None:
    assert band("price", **HIGH) == "high"  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "intent", ["complaint", "negotiation", "financing", "trade_in", "human_request"]
)
def test_what_a_person_decides_is_never_high(intent: str) -> None:
    assert band(intent, **HIGH) == "low"  # type: ignore[arg-type]


def test_the_model_asking_for_help_is_low_however_good_the_draft() -> None:
    assert band("price", **{**HIGH, "needs_human": "asked for a final price"}) == "low"  # type: ignore[arg-type]


def test_a_draft_that_needed_a_second_attempt_is_low() -> None:
    """The first one broke a guard. That is exactly when a person should read it."""
    assert band("price", **{**HIGH, "regenerated": True}) == "low"  # type: ignore[arg-type]


def test_a_message_we_barely_understood_is_low() -> None:
    assert band("price", **{**HIGH, "intent_confidence": 0.4}) == "low"  # type: ignore[arg-type]


def test_a_price_with_no_source_is_not_high() -> None:
    assert band("price", **{**HIGH, "has_sources": False}) == "medium"  # type: ignore[arg-type]


def test_a_greeting_needs_no_source_to_be_high() -> None:
    """Nothing factual is being claimed, so there is nothing to ground."""
    assert band("greeting", **{**HIGH, "has_sources": False}) == "high"  # type: ignore[arg-type]


def test_a_shaky_classification_is_medium_not_high() -> None:
    assert band("price", **{**HIGH, "intent_confidence": 0.7}) == "medium"  # type: ignore[arg-type]


def test_an_intent_with_no_rule_is_medium() -> None:
    assert band("other", **HIGH) == "medium"  # type: ignore[arg-type]


def test_low_beats_high_when_both_could_apply() -> None:
    """A regenerated, perfectly classified price answer is low, not high. The
    order in docs/sales/04-ai-copilot.md § 3 is the specification."""
    assert band("price", **{**HIGH, "regenerated": True, "intent_confidence": 1.0}) == "low"  # type: ignore[arg-type]


@pytest.mark.parametrize("value,expected", [(0.6, "medium"), (0.59, "low"), (0.85, "high")])
def test_the_thresholds_are_where_the_spec_puts_them(value: float, expected: str) -> None:
    assert band("price", **{**HIGH, "intent_confidence": value}) == expected  # type: ignore[arg-type]
