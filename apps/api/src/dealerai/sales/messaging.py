"""What may be sent to a customer, as pure functions. docs/sales/03-whatsapp.md § 6.

No database and no clock: callers pass `now`, so the rules are testable at the
exact edge — one second before the window closes — rather than approximately.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from ..core.words import Words

#: Said wherever a customer who opted out is about to be written to.
OPTED_OUT = Words("The customer asked not to be messaged.", "طلب العميل ألّا نراسله.")

_PUNCTUATION = re.compile(r"[^\w\s]")
_TATWEEL = "ـ"
_VARIABLE = re.compile(r"\{\{(\d+)\}\}")


def _normalise(text: str) -> str:
    """Remove case, accents, Arabic diacritics and hamza forms, punctuation and spacing."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    bare = "".join(c for c in decomposed if not unicodedata.combining(c)).replace(_TATWEEL, "")
    return " ".join(_PUNCTUATION.sub("", bare).split())


_OPT_OUT = frozenset(
    _normalise(phrase)
    for phrase in (
        "stop",
        "unsubscribe",
        "stop messaging me",
        "don't message me",
        "do not message me",
        "توقف",
        "إلغاء الاشتراك",
        "لا تراسلني",
        "لا ترسل لي",
        "لا ترسلوا لي",
        "arrête",
        "arrêtez",
        "stop svp",
        "désabonner",
        "se désabonner",
    )
)


def is_opt_out(text: str | None) -> bool:
    return bool(text) and _normalise(text or "") in _OPT_OUT


def window_is_open(expires_at: datetime | None, now: datetime) -> bool:
    """Free-form messages need the customer's last message to be under 24 hours old."""
    return expires_at is not None and now < expires_at


def template_block_reason(category: str, consent: Mapping[str, Any]) -> Words | None:
    """Why this template may not go to this customer, or None when it may."""
    if consent.get("opted_out_at"):
        return OPTED_OUT
    if category == "marketing" and consent.get("marketing") is not True:
        return Words(
            "Marketing templates need the customer's recorded marketing consent.",
            "القوالب التسويقية تحتاج موافقة مسجلة من العميل على الرسائل التسويقية.",
        )
    return None


def variable_numbers(body: str) -> list[int]:
    """The distinct {{n}} placeholders in a template body, in order."""
    return sorted({int(n) for n in _VARIABLE.findall(body)})


def render_template(body: str, variables: Sequence[str]) -> str:
    """Fill {{1}}, {{2}} … the way WhatsApp will, for the thread and for search."""

    def fill(match: re.Match[str]) -> str:
        index = int(match.group(1)) - 1
        return variables[index] if 0 <= index < len(variables) else match.group(0)

    return _VARIABLE.sub(fill, body)
