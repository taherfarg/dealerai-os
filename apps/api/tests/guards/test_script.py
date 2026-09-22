"""Answer in the script they wrote in."""

from __future__ import annotations

import pytest

from dealerai.guards import script

ARABIC = "السلام عليكم، هل السيارة متوفرة؟"
LATIN = "ma3ak Land Cruiser 2023 mawjood?"


def test_an_arabic_script_reply_to_a_latin_script_customer_is_blocked() -> None:
    findings = script.check("نعم، متوفرة لدينا الآن.", customer_wrote=LATIN)
    assert [finding.detail for finding in findings] == ["arabic"]
    assert "latin script" in findings[0].message


def test_a_latin_reply_to_an_arabic_script_customer_is_blocked() -> None:
    assert script.check("Yes, it is available now.", customer_wrote=ARABIC) != []


@pytest.mark.parametrize(
    "draft,customer",
    [
        ("نعم، متوفرة لدينا الآن.", ARABIC),
        ("Yes, it is available now.", LATIN),
        ("Oui, elle est disponible.", "Bonjour, elle est disponible ?"),
    ],
)
def test_the_same_script_passes(draft: str, customer: str) -> None:
    assert script.check(draft, customer_wrote=customer) == []


def test_a_model_name_does_not_change_the_script() -> None:
    """Every good Arabic reply names a Land Cruiser in Latin letters."""
    assert script.script_of("متوفرة لدينا سيارة Land Cruiser موديل 2023") == "arabic"


@pytest.mark.parametrize("text", ["OK", "👍", "+971 50 123 4567", ""])
def test_too_little_to_tell_is_not_a_violation(text: str) -> None:
    assert script.script_of(text) is None
    assert script.check("Yes, it is available now.", customer_wrote=text) == []


def test_a_customer_who_mixes_scripts_may_be_answered_either_way() -> None:
    mixed = "مرحبا هل عندكم do you have Hilux"
    assert script.script_of(mixed) is None
    assert script.check("نعم متوفرة لدينا", customer_wrote=mixed) == []


def test_a_draft_too_short_to_judge_is_left_alone() -> None:
    assert script.check("👍", customer_wrote=ARABIC) == []


def test_the_presentation_forms_an_older_keyboard_emits_are_arabic() -> None:
    """A Windows keyboard can produce U+FEFF-block forms rather than U+06xx.
    Reading those as Latin would block every reply to that customer."""
    assert script.script_of("ﻻ ﺷﻜﺮﺍ") == "arabic"
