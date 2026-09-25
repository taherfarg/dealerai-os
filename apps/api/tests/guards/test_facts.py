"""Every number in a line written from facts is one of the facts."""

from __future__ import annotations

from dealerai.guards import facts

FACTS = "- new conversations: 23\n- first reply, median: 4 min (the target is 5 min)\n- won: 1,200"


def test_numbers_the_facts_hold_pass() -> None:
    assert facts.check("23 new conversations and a 4 min median", facts=FACTS) == []


def test_a_number_the_facts_do_not_hold_is_named() -> None:
    [finding] = facts.check("37 new conversations yesterday", facts=FACTS)
    assert (finding.guard, finding.detail) == ("facts", "37")


def test_arabic_digits_are_the_numbers_they_are() -> None:
    assert facts.check("٢٣ محادثة جديدة", facts=FACTS) == []


def test_a_thousands_separator_is_not_a_new_number() -> None:
    assert facts.check("1200 won", facts=FACTS) == []


def test_a_line_without_numbers_passes() -> None:
    assert facts.check("A quiet day.", facts=FACTS) == []
