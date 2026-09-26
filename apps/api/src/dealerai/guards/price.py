"""The price guard.

This product has one zero-tolerance failure: stating a price that is not the
price. Everything else is a bad day; this is a customer arriving at a showroom
with a screenshot.

So the rule is not "check the price is right". It is **every price-shaped figure
in the text must be one we can point at a database row for**, and anything else
is blocked. A monthly instalment nobody approved, a "starting from" the agent
rounded down, a figure copied out of last month's campaign — all rejected, all
by the same rule, none needing to be anticipated.

The bias is deliberate. A false positive costs one regenerated caption. A false
negative costs the dealer a sale and their credibility.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from ..core.text import ascii_digits
from . import Finding, Findings

GUARD = "price"

#: Currency next to a number means the number is money, whatever else it looks
#: like. Includes the Arabic and abbreviated forms a Gulf caption actually uses.
CURRENCY = (
    r"AED|USD|SAR|QAR|KWD|BHD|OMR|EUR|GBP"
    r"|د\.إ|درهم|دولار|ريال|دينار|يورو"
    r"|\$|€|£"
)

#: A number followed by one of these is a measurement, not a price. Without this
#: the guard rejects every caption that mentions mileage or power, which trains
#: everyone to switch it off.
UNITS = (
    r"km|kms|kilometers?|kilometres?|miles?|mi"
    r"|hp|bhp|ps|kw|nm|lb-?ft|cc|l|litres?|liters?"
    r"|seats?|doors?|cylinders?|speed|years?|months?|days?|kg"
    # Arabic units are matched as prefixes: كيلومتر, كيلومترًا and كيلومترات are
    # all the same unit with different endings, and enumerating inflections is a
    # game with no last move. A `\b` after one of these would fail inside the
    # longer word, and "18,000 كيلومتر" would be read as a price.
    r"|كم|كيلو|حصان|مقاعد|أبواب|سنوات|سنة|سنوي|شهر|شهور|أشهر|لتر|مقعد|باب"
)

#: Below this nothing is a car price, and the market has no vehicle under a
#: thousand dirhams. Keeps "5 seats" and "3 years" out without needing every
#: unit spelled correctly.
MIN_PRICE = Decimal(1000)

#: A bare four-digit number in this range is a model year. "2023 Land Cruiser"
#: is not a price claim, and no car in this market costs 2,023.
YEAR_RANGE = range(1950, 2101)

#: `(?![A-Za-z])` rather than `\b` after the unit. A boundary is wrong in both
#: directions here: it fails inside an inflected Arabic word, and it is not
#: needed for the ASCII units because alternation backtracks — "km" tries first
#: inside "kilometres", the lookahead rejects it, and "kilometres" matches next.
#: `(?!\d)` after the thousands groups: a group is exactly three digits and then
#: *not another digit*. Without it "BYD Seal 05 2024" reads as the grouped
#: number "05 202" with a stray "4" — a price, by this guard's rules, that no
#: row holds — and every draft naming that car was blocked. The copilot eval
#: found it on its first full run.
_FIGURE = re.compile(
    rf"(?P<before>(?:{CURRENCY})\s*)?"
    r"(?P<number>\d{1,3}(?:[,\s]\d{3})+(?!\d)(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?P<k>\s*[kK](?![a-zA-Z]))?"
    rf"\s*(?P<after>(?:{CURRENCY}|{UNITS})(?![A-Za-z]))?",
    re.IGNORECASE,
)


def _value(raw: str, thousands_k: bool) -> Decimal | None:
    cleaned = raw.replace(",", "").replace(" ", "")
    try:
        value = Decimal(cleaned)
    except InvalidOperation:  # pragma: no cover - the pattern only matches digits
        return None
    return value * 1000 if thousands_k else value


def figures(text: str) -> list[tuple[Decimal, str]]:
    """Every price claim in the text, with the words it appeared as.

    Split out from `check` because *what counts as a price* is the whole
    difficulty, and it deserves to be tested on its own.
    """
    found: list[tuple[Decimal, str]] = []
    for match in _FIGURE.finditer(ascii_digits(text)):
        raw = match.group("number")
        has_k = bool(match.group("k"))
        currency = bool(match.group("before")) or _is_currency(match.group("after"))
        unit = match.group("after") and not _is_currency(match.group("after"))

        value = _value(raw, has_k)
        if value is None:  # pragma: no cover
            continue

        if currency:
            # Money, regardless of magnitude or shape. "AED 500" is a claim.
            found.append((value, match.group(0).strip()))
            continue
        if unit:
            continue
        if not has_k and "," not in raw and "." not in raw and int(value) in YEAR_RANGE:
            continue  # a model year
        if value < MIN_PRICE:
            continue
        found.append((value, match.group(0).strip()))
    return found


def _is_currency(token: str | None) -> bool:
    return bool(token) and re.fullmatch(CURRENCY, token or "", re.IGNORECASE) is not None


def check(text: str, *, allowed: set[Decimal] | None = None) -> Findings:
    """Block any price-shaped figure that is not in `allowed`.

    `allowed` is major units — 66000, not 6600000 — because that is what a
    caption says and comparing in the units the text uses is one less place to
    get a factor of a hundred wrong. It should hold the vehicle's list price and
    any approved offer, and nothing else.
    """
    permitted = allowed or set()
    findings: Findings = []
    for value, shown in figures(text):
        if value not in permitted:
            findings.append(
                Finding(
                    GUARD,
                    f"{shown!r} is not a price from the record"
                    + (
                        f"; allowed: {', '.join(str(p) for p in sorted(permitted))}"
                        if permitted
                        else ""
                    ),
                    detail=shown,
                )
            )
    return findings
