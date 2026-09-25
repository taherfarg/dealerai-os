"""Every number in a line written from facts is one of the facts.

The morning brief hands a model a block of numbers and asks for one line about
them. The way that line goes wrong is a number the block does not hold: a
rounded median, a total nobody counted, a percentage worked out in the model's
head. So the rule is the price guard's without the currency — every figure in
the text must appear in the facts, or the line is not shown.
"""

from __future__ import annotations

import re

from ..core.text import ascii_digits
from . import Finding, Findings

GUARD = "facts"

#: 1,200 and 1200 are one number; 4.5 stays 4.5. ascii_digits has already
#: turned ٢٣ into 23 and the Arabic separators into their ASCII selves.
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


def numbers_in(text: str) -> set[str]:
    return {match.replace(",", "") for match in _NUMBER.findall(ascii_digits(text))}


def check(text: str, *, facts: str) -> Findings:
    unknown = numbers_in(text) - numbers_in(facts)
    return [
        Finding(guard=GUARD, message="a number that is not in the facts", detail=number)
        for number in sorted(unknown)
    ]
