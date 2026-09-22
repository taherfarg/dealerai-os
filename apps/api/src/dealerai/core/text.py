"""Text normalisation shared by anything that reads a dealer's own writing.

Small on purpose. It lives here rather than in one of its callers because the
CSV importer and the price guard must agree exactly on what a digit is — a
figure the importer accepted and the guard cannot see is the gap through which
a wrong price reaches a customer.
"""

from __future__ import annotations

import re
import unicodedata

#: Arabic separators, which are distinct characters from the ASCII ones and are
#: what an Arabic keyboard actually produces. Without these ٦٦٬٠٠٠ becomes
#: "66٬000", the price guard reads two numbers where there is one, and a
#: caption quoting the wrong price in Arabic sails straight through.
_SEPARATORS = {
    "٬": ",",  # Arabic thousands separator
    "٫": ".",  # Arabic decimal separator
    "،": ",",  # Arabic comma
    "’": ",",  # right single quote, used as a thousands mark in some exports
}

_TABLE = {ord(k): v for k, v in _SEPARATORS.items()}


def ascii_digits(text: str) -> str:
    """Arabic-Indic numerals and separators to their ASCII equivalents.

    A UAE dealer's spreadsheet really does contain ١٦٥٠٠٠, and a caption written
    in Arabic really does quote the price as ٢٦٥٬٠٠٠ درهم.
    """
    converted = "".join(str(unicodedata.digit(c)) if c.isdigit() else c for c in text)
    return converted.translate(_TABLE)


def contains_word(haystack: str, needle: str) -> bool:
    """Substring match, with word boundaries where the language has them.

    A plain substring test flags "guaranteed" inside "unguaranteed" and, far
    worse, flags Arabic words inside longer Arabic words constantly, because
    Arabic prefixes attach directly to the word. Falling back to a substring
    test for non-ASCII is the honest trade: over-flagging Arabic beats missing
    it, and a guard that misses is a guard that is not there.

    Shared by the brand and commitments guards. Two copies of a matcher whose
    whole subtlety is Arabic prefixes would be two behaviours.
    """
    if not needle.isascii():
        return needle.casefold() in haystack.casefold()
    # A boundary only means something next to a word character. "#1" has none on
    # its left, and \b there asserts a transition that never happens — so the
    # single most common unsupportable claim would never match.
    left = r"\b" if needle[:1].isalnum() else ""
    right = r"\b" if needle[-1:].isalnum() else ""
    return re.search(rf"{left}{re.escape(needle)}{right}", haystack, re.IGNORECASE) is not None
