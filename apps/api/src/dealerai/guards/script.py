"""The script guard: answer in the script they wrote in.

Half of Pollux's customers write Arabic in Latin letters — "ma3ak Land Cruiser
2023?" — and a model handed that will often answer in fully vowelled Modern
Standard Arabic. That is not a tone problem. It is a reply the customer has to
work to read, from a dealership that looks like it did not notice who it was
talking to.

ponytail: Arabic script versus Latin script, and nothing finer. It cannot tell
English from French. Upgrade trigger: "wrong language" becomes a top-three
discard reason in the acceptance report — then add language identification.
"""

from __future__ import annotations

from . import Finding, Findings

GUARD = "script"

#: The Arabic blocks a customer's keyboard actually produces: Arabic, Arabic
#: Supplement, and the presentation forms some older Windows keyboards emit.
_ARABIC_RANGES = ((0x0600, 0x06FF), (0x0750, 0x077F), (0xFB50, 0xFDFF), (0xFE70, 0xFEFF))

#: Below this there is nothing to judge. "OK", an emoji, or a bare phone number
#: says nothing about which script the customer wants.
MIN_LETTERS = 4
#: What counts as written in a script rather than containing a word of it. A
#: model name stays Latin inside an Arabic sentence, always.
MAJORITY = 0.6


def _is_arabic(char: str) -> bool:
    point = ord(char)
    return any(low <= point <= high for low, high in _ARABIC_RANGES)


def script_of(text: str) -> str | None:
    """`"arabic"`, `"latin"`, or None when there is not enough to tell."""
    arabic = sum(1 for char in text if _is_arabic(char))
    latin = sum(1 for char in text if char.isascii() and char.isalpha())
    total = arabic + latin
    if total < MIN_LETTERS:
        return None
    if arabic / total >= MAJORITY:
        return "arabic"
    if latin / total >= MAJORITY:
        return "latin"
    return None  # genuinely mixed: the customer switches, so the draft may too


def check(draft: str, *, customer_wrote: str) -> Findings:
    """Block a reply in the other script from the one the customer is using."""
    theirs = script_of(customer_wrote)
    ours = script_of(draft)
    if theirs is not None and ours is not None and theirs != ours:
        return [
            Finding(
                GUARD,
                f"the customer is writing in {theirs} script and this reply is in {ours}",
                detail=ours,
            )
        ]
    if theirs == "latin":
        # One word of Arabic script in a Latin reply is still a word they
        # cannot type back. The eval's Arabizi drafts kept writing "سعر"
        # mid-sentence after the prompt said so three different ways. The other
        # way round is fine: every good Arabic reply names a car in Latin.
        stray = next((word for word in draft.split() if any(map(_is_arabic, word))), None)
        if stray is not None:
            return [
                Finding(
                    GUARD,
                    f"the customer is writing in latin script and this reply has "
                    f"a word in Arabic script: {stray!r}",
                    detail=stray,
                )
            ]
    return []
