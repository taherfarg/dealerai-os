"""One thing to tell somebody, in each language the app speaks."""

from __future__ import annotations

from typing import NamedTuple


class Words(NamedTuple):
    """Both written where the thing is said, so whoever changes the one sees
    the other; which is used is decided where its reader is known."""

    en: str
    ar: str


def same(text: str) -> Words:
    """What is data in either language: a customer's name, a title somebody
    typed, a line the model wrote for the team. Said by name, so that giving
    one sentence twice is never mistaken for having translated it."""
    return Words(text, text)


def named(text: str) -> str:
    """A name inside a sentence, kept apart from the sentence's direction:
    FIRST STRONG ISOLATE … POP DIRECTIONAL ISOLATE. Without them a Latin name at
    the start of an Arabic sentence turns the whole line left to right — in the
    bell, and on a phone's lock screen — and an Arabic name does the same to an
    English one."""
    return f"\u2068{text}\u2069"


def someone(name: str | None) -> Words:
    """The customer by name — or, when we have none, as each language says it."""
    return same(named(name)) if name else Words("A customer", "أحد العملاء")
