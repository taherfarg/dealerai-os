"""The commitments guard: what a draft may not promise on the dealer's behalf.

The price guard covers figures. This one covers the promises with no figure in
them — a discount, a final price, a delivery date, finance approval, what a
trade-in is worth. Every one of those is a negotiation the dealership has not
had yet, and a customer holding one in writing has been promised it. In this
market they will bring the screenshot.

The empty follow-up is here too, and not by accident. "Just checking in" is the
sentence that makes a dealership's number worth blocking, and it is the first
thing a model writes when asked to follow up with nothing new to say
(docs/sales/04-ai-copilot.md § 6).

Arabic and French are not translations of the English list. They are the
phrases these customers actually receive, which is why the lists are different
lengths.
"""

from __future__ import annotations

import re

from ..core.text import ascii_digits, contains_word
from . import Finding, Findings

GUARD = "commitments"

#: code -> (what it is, the phrases). Matched with word boundaries in ASCII and
#: as substrings in Arabic (core/text.py explains why).
PHRASES: dict[str, tuple[str, tuple[str, ...]]] = {
    "discount": (
        "offers a discount, which only a person may do",
        (
            "discount",
            "% off",
            "percent off",
            "off the price",
            "special price for you",
            # Matching another dealer is a discount by another name, and the
            # eval's drafts kept offering to "see if we can match your offer"
            # after the prompt said not to.
            "match your offer",
            "match the offer",
            "match that offer",
            "match the price",
            "match that price",
            "match their price",
            "matching the price",
            "matching the offer",
            "matching your offer",
            "matching their price",
            "price match",
            "خصم",
            "تخفيض",
            "سعر خاص لك",
            "نطابق السعر",
            "نطابق العرض",
            "remise",
            "réduction",
            "rabais",
            "prix spécial pour vous",
            "aligner notre prix",
            "aligner nos prix",
        ),
    ),
    "final_price": (
        "calls a price final, which ends a negotiation nobody has had",
        (
            "final price",
            "last price",
            "best i can do",
            "lowest i can go",
            "السعر النهائي",
            "آخر سعر",
            "أقل سعر",
            "prix final",
            "dernier prix",
        ),
    ),
    "delivery": (
        "promises when the car will arrive",
        (
            "delivery by",
            "deliver it by",
            "deliver by",
            "ready by",
            "will arrive on",
            "will be delivered",
            "guaranteed delivery",
            "التسليم خلال",
            "نسلمها",
            "سيصل خلال",
            "التوصيل خلال",
            "livraison sous",
            "livré le",
            "livraison garantie",
        ),
    ),
    "finance": (
        "promises a financing decision the bank has not made",
        (
            "you are approved",
            "you're approved",
            "approved for finance",
            "financing is approved",
            "guaranteed approval",
            "no down payment needed",
            "تمت الموافقة",
            "التمويل مضمون",
            "موافقة مضمونة",
            "financement approuvé",
            "accord garanti",
        ),
    ),
    "trade_in": (
        "values a trade-in without anyone seeing the car",
        (
            "we will give you",
            "we'll give you",
            "your car is worth",
            "worth at least",
            "قيمة سيارتك",
            "سنعطيك مقابل",
            "nous vous donnerons",
            "votre voiture vaut",
        ),
    ),
    "empty_followup": (
        "says nothing — a follow-up needs a reason the customer can read",
        (
            "just checking in",
            "just following up",
            "touching base",
            "any update",
            "any news",
            "circling back",
            "أطمئن عليك",
            "أتابع معك",
            "مجرد تذكير",
            "هل من جديد",
            "je reviens vers vous",
            "petit rappel",
            "des nouvelles",
        ),
    ),
}

#: A trade-in phrase is only a promise when a figure is next to it. "We will
#: give you a call" is not a valuation, and blocking it would train everyone to
#: switch the guard off.
_NEEDS_A_FIGURE = frozenset({"trade_in"})
_FIGURE_NEAR = re.compile(r"\d[\d,. ]{2,}")
_WINDOW = 60


def check(text: str, *, replying: bool = False) -> Findings:
    """Every promise in the text, named so the model can be told what to change.

    `replying` is an inbox draft answering what the customer just wrote, which
    cannot be an empty follow-up — and there "je reviens vers vous" is "I will
    come back to you", the holding line the copilot is told to write. The eval
    watched that block a French draft twice over.
    """
    haystack = ascii_digits(text)
    findings: Findings = []
    for code, (message, phrases) in PHRASES.items():
        if replying and code == "empty_followup":
            continue
        for phrase in phrases:
            if not contains_word(haystack, phrase):
                continue
            if code in _NEEDS_A_FIGURE and not _figure_near(haystack, phrase):
                continue
            findings.append(Finding(GUARD, f"{message}: {phrase!r}", detail=phrase))
            break  # one finding per code; the model fixes the sentence, not the list
    return findings


def _figure_near(haystack: str, phrase: str) -> bool:
    """Is there a number within a sentence of this phrase?

    The window is what keeps "we will give you a call … the Hilux is AED
    165,000" out: a price three clauses away is a price, not a valuation.
    """
    # Both sides folded, and the slice taken from the folded string: casefold
    # is not length-preserving in every language, and slicing one with an index
    # found in the other is how a window silently lands in the wrong place.
    folded = haystack.casefold()
    index = folded.find(phrase.casefold())
    return bool(_FIGURE_NEAR.search(folded[index : index + len(phrase) + _WINDOW]))
