"""The PII guard: a customer's details must not leave in public content.

The failure this prevents is mundane and awful — a reply drafted from a private
WhatsApp thread, posted as a public comment, carrying the customer's phone
number. It redacts rather than blocks, because the content itself is usually
fine and the number is a slip.

Not a compliance certificate. It catches the shapes that actually appear in a
dealership's outbound text; the legal position is docs/00-prd.md § PDPL.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from difflib import SequenceMatcher

from ..core.text import ascii_digits
from . import Finding, Findings

GUARD = "pii"

EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")

#: UAE mobiles as they are actually written: +971 50 123 4567, 0501234567,
#: 971-55-1234567. Also matches the neighbouring Gulf country codes, since an
#: exporter's customers are rarely all local.
PHONE = re.compile(r"(?:\+?9(?:71|66|65|68|73|74)|\b0)[\s.-]?\d(?:[\s.-]?\d){7,10}\b")

#: Emirates ID: 784-YYYY-NNNNNNN-C.
EMIRATES_ID = re.compile(r"\b784[-\s]?\d{4}[-\s]?\d{7}[-\s]?\d\b")

REDACTION = "[redacted]"

_PATTERNS = (
    ("an email address", EMAIL),
    ("an Emirates ID", EMIRATES_ID),
    ("a phone number", PHONE),
)


def redact(text: str) -> tuple[str, Findings]:
    """Return the text with PII removed, and what was removed.

    Emirates ID before phone: an ID is a long run of digits that the phone
    pattern would otherwise eat half of, leaving the rest of the number visible,
    which is worse than either outcome.
    """
    findings: Findings = []
    cleaned = ascii_digits(text)
    for label, pattern in _PATTERNS:
        for match in pattern.finditer(cleaned):
            findings.append(
                Finding(GUARD, f"outbound content contains {label}", detail=match.group())
            )
        cleaned = pattern.sub(REDACTION, cleaned)
    return cleaned, findings


def check(text: str) -> Findings:
    return redact(text)[1]


#: Words of overlap that mean a note was quoted rather than agreed with. Short
#: runs are the model saying the same thing, which is what the note is for.
NOTE_RUN_WORDS = 8


def check_outbound(text: str, *, own_contacts: set[str], notes: Sequence[str] = ()) -> Findings:
    """What a reply to *this* customer may not contain.

    Different from `check`, which is for public content and treats every number
    as a leak. A reply should be able to give the showroom's own number.

    Two failures, one place. A phone number, email or Emirates ID that is not
    one of the dealership's own published details belongs to somebody — most
    likely another customer, whose thread the model has no business
    remembering. And an internal note is written *about* a customer, not *to*
    them: "he is desperate, push the Prado" reads very differently when it
    arrives on their phone.

    `own_contacts` are compared by their last few digits, so neither formatting
    nor a country code can hide one: "+971 4 123 4567" and "04-123-4567" are
    the same showroom.

    ponytail: a suffix comparison, not a phone-number library. It can be fooled
    by a stranger's number ending in the same seven digits, which costs one
    un-blocked number that is almost ours. The alternative — matching only the
    exact string — blocks every draft that gives out the showroom number in the
    local format, which is how a guard gets switched off. Upgrade trigger: a
    real collision, or a tenant with numbers in several countries.
    """
    permitted = {_key(value) for value in own_contacts}
    findings: Findings = []
    cleaned = ascii_digits(text)
    for label, pattern in _PATTERNS:
        for match in pattern.finditer(cleaned):
            found = match.group()
            if _key(found) in permitted:
                continue
            findings.append(
                Finding(
                    GUARD,
                    f"this reply contains {label} that is not the dealership's own",
                    detail=found,
                )
            )

    words = _words(cleaned)
    for note in notes:
        run = _longest_run(words, _words(ascii_digits(note)))
        if run >= NOTE_RUN_WORDS:
            findings.append(
                Finding(
                    GUARD,
                    f"{run} words of an internal note are quoted back to the customer",
                    detail=note[:80],
                )
            )
    return findings


#: How much of a number identifies it. The subscriber part, which is what a
#: person recognises as "our number" whichever way it was written.
_SIGNIFICANT_DIGITS = 7


def _key(value: str) -> str:
    """What two ways of writing the same contact detail have in common."""
    digits = "".join(char for char in value if char.isdigit())
    if len(digits) >= _SIGNIFICANT_DIGITS:
        return digits[-_SIGNIFICANT_DIGITS:]
    return digits or value.casefold()


def _words(text: str) -> list[str]:
    return re.findall(r"\w+", text.casefold())


def _longest_run(left: list[str], right: list[str]) -> int:
    """The longest run of words the two share, by difflib's own matcher.

    `autojunk` off: it treats anything appearing in more than 1% of a long
    sequence as noise, which for word lists means "the" and "you" — exactly the
    words that hold a quoted sentence together.
    """
    if not left or not right:
        return 0
    return SequenceMatcher(a=left, b=right, autojunk=False).find_longest_match().size
