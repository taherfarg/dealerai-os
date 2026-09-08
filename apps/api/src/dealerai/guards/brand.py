"""The brand guard: does this sound like the dealership, and is it legal?

Everything here comes from the tenant's confirmed brand profile — a human
approved these rules, so enforcing them is not second-guessing the model, it is
holding it to something the dealer signed off.

Deliberately not a style critic. "Is this good copy?" is not a guard, it is an
opinion, and a guard that blocks on opinions gets switched off within a week.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import Finding, Findings

GUARD = "brand"

#: Superlatives a dealer cannot substantiate. Claiming to be the cheapest is a
#: comparative advertising problem in every Gulf market, and it is the phrase a
#: model reaches for first when asked to sound confident.
UNSUPPORTABLE = (
    "best price",
    "cheapest",
    "lowest price",
    "guaranteed",
    "number one",
    "no. 1",
    "#1",
    "best in the world",
    "unbeatable",
    "أرخص",
    "الأفضل في العالم",
    "مضمون",
)

MAX_HASHTAGS = 8


@dataclass(frozen=True, slots=True)
class BrandRules:
    """The subset of a confirmed brand profile a guard can check mechanically."""

    forbidden_words: tuple[str, ...] = ()
    #: Legal wording this market requires — VAT notice, finance disclaimer.
    required_disclaimer: str | None = None
    #: At least one of these must appear. Empty means the dealer has no
    #: preference, not that any CTA will do.
    allowed_ctas: tuple[str, ...] = ()
    max_hashtags: int = MAX_HASHTAGS
    allow_unsupportable_claims: bool = False
    banned_emoji: tuple[str, ...] = field(default=())


def _contains(haystack: str, needle: str) -> bool:
    """Word-boundary match where the language has word boundaries.

    A plain substring test flags "guaranteed" inside "unguaranteed" and, worse,
    flags Arabic words inside longer Arabic words constantly, because Arabic
    prefixes attach directly. Falling back to a substring test for non-ASCII is
    the honest trade: over-flagging Arabic beats missing it.
    """
    if not needle.isascii():
        return needle in haystack
    # A boundary only means something next to a word character. "#1" has none on
    # its left, and \b there asserts a transition that never happens — so the
    # single most common unsupportable claim would never match.
    left = r"\b" if needle[:1].isalnum() else ""
    right = r"\b" if needle[-1:].isalnum() else ""
    return re.search(rf"{left}{re.escape(needle)}{right}", haystack, re.IGNORECASE) is not None


def check(text: str, rules: BrandRules | None = None) -> Findings:
    rules = rules or BrandRules()
    findings: Findings = []
    lowered = text.lower()

    for word in rules.forbidden_words:
        if _contains(lowered, word.lower()):
            findings.append(Finding(GUARD, f"contains the forbidden word {word!r}", detail=word))

    if not rules.allow_unsupportable_claims:
        for claim in UNSUPPORTABLE:
            if _contains(lowered, claim):
                findings.append(
                    Finding(
                        GUARD,
                        f"claims {claim!r}, which the dealer cannot substantiate",
                        detail=claim,
                    )
                )

    if rules.required_disclaimer and rules.required_disclaimer.lower() not in lowered:
        findings.append(
            Finding(
                GUARD,
                "the disclaimer this market requires is missing",
                detail=rules.required_disclaimer,
            )
        )

    if rules.allowed_ctas and not any(
        _contains(lowered, cta.lower()) for cta in rules.allowed_ctas
    ):
        findings.append(
            Finding(
                GUARD,
                "no approved call to action",
                detail=", ".join(rules.allowed_ctas),
            )
        )

    hashtags = re.findall(r"#\w+", text)
    if len(hashtags) > rules.max_hashtags:
        findings.append(
            Finding(
                GUARD,
                f"{len(hashtags)} hashtags, more than the {rules.max_hashtags} allowed",
                detail=" ".join(hashtags[rules.max_hashtags :]),
            )
        )

    for emoji in rules.banned_emoji:
        if emoji in text:
            findings.append(Finding(GUARD, f"uses the banned emoji {emoji}", detail=emoji))

    return findings
