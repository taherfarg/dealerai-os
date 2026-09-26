"""A new customer's language, from their first message, for routing."""

from __future__ import annotations

import pytest

from dealerai.sales.language import language_of


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("السلام عليكم، عندكم هايلكس ٢٠٢٦ ديزل؟", "ar"),
        ("3andkom hilux? bkam?", "ar"),
        ("salam, ma3ak land cruiser?", "ar"),
        ("Bonjour, vous exportez vers Dakar ? Je cherche un Land Cruiser.", "fr"),
        ("Le prix pour Oran, tout compris ?", "fr"),
        ("Merci, j'ai acheté ailleurs.", "fr"),
        ("Hello, do you have the BYD Seal 05 in blue?", "en"),
        ("Is the Hilux GR Sport still available?", "en"),
        ("Audi Q7 price?", "en"),
    ],
)
def test_the_language_they_wrote_in(text: str, expected: str) -> None:
    assert language_of(text) == expected


@pytest.mark.parametrize("text", ["OK", "👍", "Q7?", "AED 128,000", "Land Cruiser"])
def test_too_little_to_tell_is_not_a_guess(text: str) -> None:
    """The next message decides: a wrong guess would route them for good."""
    assert language_of(text) is None
