"""Text normalisation shared by anything that reads a dealer's own writing.

Small on purpose. It lives here rather than in one of its callers because the
CSV importer and the price guard must agree exactly on what a digit is — a
figure the importer accepted and the guard cannot see is the gap through which
a wrong price reaches a customer.
"""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation

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


def parse_number(raw: str) -> Decimal:
    """A number out of whatever a spreadsheet cell or an invoice line said.

    Separator rules, in order:
      * both `,` and `.` present — the last one is the decimal point
      * one kind only, exactly three digits after the last — thousands
        ("165.000", "1,250,000")
      * anything else — decimal ("165.50", "3.6725")

    The middle rule is the one that matters: reading "165.000" as 165 prices a
    Land Cruiser at 165 dirhams, and it is the failure a dealer would not spot
    until a customer arrived to buy it.

    And it is *exactly* three. A thousands group always has three digits, so
    four after a separator can only be decimals — reading "3.6725" as 36725
    records an exchange rate ten thousand times too large, and every cost
    converted with it.
    """
    # ponytail: this misreads a genuine 3-decimal KWD amount as thousands. No
    # car costs 1.5 KWD, so the trade is right; revisit if fils-level prices
    # ever appear in an import.
    text = ascii_digits(raw).strip()
    kept = "".join(c for c in text if c.isdigit() or c in ",.-")
    if not any(c.isdigit() for c in kept):
        raise ValueError(f"no number in {raw!r}")

    last = max(kept.rfind(","), kept.rfind("."))
    if last == -1:
        cleaned = kept
    else:
        after = len(kept) - last - 1
        head = kept[:last].replace(",", "").replace(".", "")
        tail = kept[last + 1 :]
        thousands = after == 3 and not ("," in kept and "." in kept)
        cleaned = head + tail if thousands else f"{head}.{tail}"
    try:
        return Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(f"could not read a number from {raw!r}") from exc
