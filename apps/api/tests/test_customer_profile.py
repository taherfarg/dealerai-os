"""Who set what, and what that costs the next writer. Pure — no database."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from dealerai.core.errors import Unusable
from dealerai.sales.profile import apply

NOW = datetime(2026, 9, 21, 10, 0, tzinfo=UTC)
MESSAGE_ID = "3f1a9f1e-0000-4000-8000-000000000001"


def test_the_ai_may_fill_a_blank_and_correct_itself() -> None:
    first = apply({}, {"budget": {"amount_minor": 15_000_000}}, source="ai", now=NOW)
    second = apply(first, {"budget": {"amount_minor": 14_000_000}}, source="ai", now=NOW)
    assert second["budget"]["value"] == {"amount_minor": 14_000_000, "currency": "AED"}
    assert second["budget"]["source"] == "ai"


def test_what_a_person_set_is_not_overwritten_by_a_later_guess() -> None:
    mine = apply({}, {"timeline": "This week"}, source="human", now=NOW)
    later = apply(mine, {"timeline": "Next month"}, source="ai", now=NOW)
    assert later["timeline"]["value"] == "This week"
    assert later["timeline"]["source"] == "human"


def test_editing_an_ai_value_makes_it_a_person_s() -> None:
    guessed = apply({}, {"interest": "Hilux"}, source="ai", now=NOW, evidence_message_id=MESSAGE_ID)
    assert guessed["interest"]["evidence_message_id"] == MESSAGE_ID

    corrected = apply(guessed, {"interest": "Land Cruiser"}, source="human", now=NOW)
    assert corrected["interest"]["source"] == "human"
    assert corrected["interest"]["evidence_message_id"] is None, (
        "a person's answer does not come from a message the model read"
    )


def test_a_person_can_clear_a_field() -> None:
    held = {"trade_in": {"value": True, "source": "ai", "evidence_message_id": None}}
    assert apply(held, {"trade_in": None}, source="human", now=NOW) == {}


def test_clearing_a_field_the_ai_owns_leaves_the_rest_alone() -> None:
    held = apply({}, {"interest": "Hilux", "timeline": "This week"}, source="ai", now=NOW)
    left = apply(held, {"timeline": None}, source="human", now=NOW)
    assert set(left) == {"interest"}


def test_a_field_we_do_not_record_is_refused_by_name() -> None:
    with pytest.raises(Unusable, match="shoe_size"):
        apply({}, {"shoe_size": 44}, source="human", now=NOW)


@pytest.mark.parametrize(
    "key,value",
    [
        ("purchase_type", "maybe"),
        ("payment", "crypto"),
        ("destination", "Algeria"),
        ("budget", "a lot"),
        ("budget", {"amount_minor": 1_000_000, "currency": "dirhams"}),
        ("objections", "too expensive"),
    ],
)
def test_a_value_that_is_not_one_of_the_allowed_ones_is_refused(key: str, value: Any) -> None:
    with pytest.raises(Unusable):
        apply({}, {key: value}, source="human", now=NOW)


def test_a_country_is_stored_the_way_the_flag_lookup_expects_it() -> None:
    stored = apply({}, {"destination": "dz"}, source="human", now=NOW)
    assert stored["destination"]["value"] == "DZ"


def test_a_long_objection_list_cannot_grow_without_end() -> None:
    stored = apply({}, {"objections": [f"reason {n}" for n in range(50)]}, source="ai", now=NOW)
    assert len(stored["objections"]["value"]) == 20


def test_every_value_carries_when_it_was_set() -> None:
    stored = apply({}, {"interest": "Hilux"}, source="ai", now=NOW)
    assert stored["interest"]["updated_at"] == NOW.isoformat()
