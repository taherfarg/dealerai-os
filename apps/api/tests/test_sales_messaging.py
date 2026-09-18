"""The send rules at their edges. No database."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from dealerai.sales.messaging import (
    is_opt_out,
    render_template,
    template_block_reason,
    variable_numbers,
    window_is_open,
)

NOW = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "text",
    [
        "STOP",
        "Stop.",
        "  stop  ",
        "unsubscribe",
        "Don't message me",
        "لا تراسلني",
        "إلغاء الاشتراك",
        "توقف!",
        "Arrêtez",
        "Se désabonner",
    ],
)
def test_opt_out_phrases_in_three_languages(text: str) -> None:
    assert is_opt_out(text)


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "Can you stop by the showroom tomorrow?",
        "stop, the price is too high",
        "توقف السعر عند كم؟",
        "Arrêtez-vous à Oran ?",
    ],
)
def test_ordinary_messages_are_not_opt_outs(text: str | None) -> None:
    """Whole messages, not words: a customer saying "stop by" is still a customer."""
    assert not is_opt_out(text)


def test_the_window_is_open_until_its_last_instant() -> None:
    expires = NOW + timedelta(hours=24)
    assert window_is_open(expires, expires - timedelta(seconds=1))
    assert not window_is_open(expires, expires)
    assert not window_is_open(None, NOW)


def test_an_opt_out_blocks_every_template() -> None:
    consent = {"opted_out_at": "2026-09-01T10:00:00Z", "marketing": True}
    assert template_block_reason("utility", consent)
    assert template_block_reason("marketing", consent)


def test_marketing_needs_a_recorded_yes() -> None:
    assert template_block_reason("marketing", {})
    assert template_block_reason("marketing", {"marketing": "yes"})
    assert template_block_reason("marketing", {"marketing": True}) is None
    assert template_block_reason("utility", {}) is None


def test_render_template_fills_numbered_variables() -> None:
    body = "Hi {{1}}, the {{2}} is now {{3}}."
    assert (
        render_template(body, ["Karim", "Hilux GR Sport", "AED 165,000"])
        == "Hi Karim, the Hilux GR Sport is now AED 165,000."
    )
    assert render_template("Hi {{1}} {{2}}", ["Karim"]) == "Hi Karim {{2}}"


def test_variable_numbers_are_distinct_and_ordered() -> None:
    assert variable_numbers("{{2}} and {{1}} and {{2}} again") == [1, 2]
    assert variable_numbers("no variables") == []
