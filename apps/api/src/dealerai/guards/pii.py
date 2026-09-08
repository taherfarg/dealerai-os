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
