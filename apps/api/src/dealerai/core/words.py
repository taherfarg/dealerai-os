"""One thing to tell somebody, in each language the app speaks."""

from __future__ import annotations

from typing import NamedTuple


class Words(NamedTuple):
    """Both written where the thing is said, so whoever changes the one sees
    the other; which is used is decided where its reader is known."""

    en: str
    ar: str
