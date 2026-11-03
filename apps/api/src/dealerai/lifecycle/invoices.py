"""Reading a purchase document into cost lines a person confirms.

An auction receipt, a shipping invoice, a customs receipt, a workshop bill — a
photograph or a PDF in, *proposed* cost lines out. Nothing here writes a row.
`POST /v1/vehicles/{id}/costs` writes what a person posted back, so there is no
path from a model's reading to a stored cost that a person did not look at —
the same rule as the CSV import.

What the model is not trusted with:

* **An amount.** Each line comes with the text it was read from, and code checks
  the amount is in that text. A figure with no quote, or a quote that does not
  contain it, is not proposed.
* **The arithmetic.** If the document prints a total, the lines must add up to
  it. Dropping a line and doubling one are the two usual misreadings, and a sum
  catches both without believing anything.
* **An exchange rate.** Only one printed on the document, verified the same way.
  A rate from a model's memory is a guess with four decimal places.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

import structlog
from google.genai import types
from pydantic import BaseModel, Field

from ..ai.gateway import SystemLayers, complete
from ..ai.models import TaskKind
from ..ai.prompts import load
from ..core.money import Money
from ..core.text import ascii_digits, parse_number

log = structlog.get_logger()

Category = Literal[
    "purchase",
    "auction_fee",
    "transport",
    "shipping",
    "customs",
    "registration",
    "inspection",
    "repair",
    "parts",
    "detailing",
    "photography",
    "storage",
    "commission",
    "other",
]

#: What a person may upload. A photograph from a phone is the common case; a
#: PDF is what an auction house emails.
MIME_TYPES = frozenset({"image/jpeg", "image/png", "image/webp", "application/pdf"})
MAX_BYTES = 15 * 1024 * 1024

#: A difference this small between the lines and the printed total is rounding
#: on the document, not a misreading — one minor unit per line, at most.
ROUNDING_SLACK_PER_LINE = 1


class ReadLine(BaseModel):
    category: Category
    description: str = Field(max_length=300)
    amount: str = Field(description="The amount exactly as printed, e.g. '1,250.00'.")
    quote: str = Field(
        max_length=400,
        description="The line of the document this amount was read from, copied as printed.",
    )


class Reading(BaseModel):
    """What the model is asked for. Everything is text as printed; code parses."""

    currency: str = Field(
        min_length=3, max_length=3, description="ISO code of the currency the document uses."
    )
    vendor: str | None = Field(default=None, max_length=200)
    reference: str | None = Field(
        default=None, max_length=120, description="Invoice, receipt or lot number."
    )
    document_date: str | None = Field(default=None, description="As YYYY-MM-DD, if printed.")
    lines: list[ReadLine] = Field(default_factory=list)
    total: str | None = Field(default=None, description="The grand total exactly as printed.")
    total_quote: str | None = Field(default=None, max_length=400)
    fx_rate: str | None = Field(
        default=None, description="An exchange rate only if one is printed on the document."
    )
    fx_quote: str | None = Field(default=None, max_length=400)


@dataclass(frozen=True, slots=True)
class ProposedLine:
    category: str
    description: str
    amount_minor: int
    currency: str
    quote: str


@dataclass(slots=True)
class Proposal:
    currency: str
    vendor: str | None
    reference: str | None
    incurred_at: date | None
    lines: list[ProposedLine]
    total_minor: int | None
    #: Only when printed on the document and found in its own quote.
    fx_rate: Decimal | None
    #: Things the person must look at before confirming. Not errors: the
    #: proposal is still shown, with these in red.
    warnings: list[str] = field(default_factory=list)


_NUMBER = re.compile(r"\d[\d.,\s]*\d|\d")


def numbers_in(text: str) -> list[Decimal]:
    """Every number in a line of text, read with the CSV importer's rules."""
    found: list[Decimal] = []
    for token in _NUMBER.findall(ascii_digits(text)):
        # A run like "2 1,250.00" is two numbers with a space between, and a
        # space-grouped thousand is one: try the whole token, then its parts.
        for candidate in (token, *token.split()):
            try:
                found.append(parse_number(candidate))
            except ValueError:
                continue
    return found


def _amount_in_quote(amount: Decimal, quote: str) -> bool:
    return amount in numbers_in(quote)


def _date(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw.strip()[:10])
    except ValueError:
        return None


def verify(reading: Reading) -> Proposal:
    """Keep what is provably on the document; say what does not add up.

    Pure, so every rule is testable without a model and holds whatever the
    model returns.
    """
    currency = reading.currency.strip().upper()
    warnings: list[str] = []
    lines: list[ProposedLine] = []

    for line in reading.lines:
        try:
            amount = parse_number(line.amount)
        except ValueError:
            warnings.append(f"skipped {line.description!r}: {line.amount!r} is not a number")
            continue
        if amount <= 0:
            warnings.append(f"skipped {line.description!r}: an amount of {line.amount}")
            continue
        if not _amount_in_quote(amount, line.quote):
            # The amount is not in the text the model says it read it from. It
            # may be right; it is not shown as if it were checked.
            warnings.append(
                f"skipped {line.description!r}: {line.amount} does not appear in "
                f"its own line of the document"
            )
            continue
        try:
            money = Money.from_major(amount, currency)
        except ValueError:
            warnings.append(
                f"skipped {line.description!r}: {line.amount} is not a {currency} amount"
            )
            continue
        lines.append(
            ProposedLine(
                category=line.category,
                description=line.description.strip(),
                amount_minor=money.amount_minor,
                currency=currency,
                quote=line.quote.strip(),
            )
        )

    total_minor: int | None = None
    if reading.total:
        try:
            total = parse_number(reading.total)
            if reading.total_quote and not _amount_in_quote(total, reading.total_quote):
                warnings.append(f"the total {reading.total} does not appear where it was read")
            else:
                total_minor = Money.from_major(total, currency).amount_minor
        except ValueError:
            warnings.append(f"could not read the total {reading.total!r}")

    if total_minor is not None:
        summed = sum(line.amount_minor for line in lines)
        slack = ROUNDING_SLACK_PER_LINE * max(len(lines), 1)
        if abs(summed - total_minor) > slack:
            difference = Money(abs(summed - total_minor), currency)
            warnings.append(
                f"the lines add up to {Money(summed, currency)} but the document's total is "
                f"{Money(total_minor, currency)} — {difference} "
                f"{'missing' if summed < total_minor else 'too much'}"
            )

    fx_rate: Decimal | None = None
    if reading.fx_rate:
        try:
            rate = parse_number(reading.fx_rate)
            if rate > 0 and reading.fx_quote and _amount_in_quote(rate, reading.fx_quote):
                fx_rate = rate
            else:
                warnings.append(f"the exchange rate {reading.fx_rate} was not found where read")
        except ValueError:
            warnings.append(f"could not read the exchange rate {reading.fx_rate!r}")

    return Proposal(
        currency=currency,
        vendor=(reading.vendor or "").strip() or None,
        reference=(reading.reference or "").strip() or None,
        incurred_at=_date(reading.document_date),
        lines=lines,
        total_minor=total_minor,
        fx_rate=fx_rate,
        warnings=warnings,
    )


async def read(
    *, tenant_id: UUID, data: bytes, mime_type: str, hint: str | None = None
) -> Proposal:
    """Read one document. Costs one vision call; writes nothing."""
    turn = types.Content(
        role="user",
        parts=[
            types.Part.from_bytes(data=data, mime_type=mime_type),
            types.Part.from_text(
                text="Read the costs on this document."
                + (f"\n\n<untrusted>\n{hint}\n</untrusted>" if hint else "")
            ),
        ],
    )
    result = await complete(
        TaskKind.VISION,
        tenant_id=tenant_id,
        system=SystemLayers(role=load("invoice_reader")),
        messages=turn,
        output_schema=Reading,
        trace_name="invoice_reader",
    )
    assert isinstance(result.parsed, Reading)  # noqa: S101 - schema-constrained
    proposal = verify(result.parsed)
    log.info(
        "invoice_read",
        lines=len(proposal.lines),
        read=len(result.parsed.lines),
        warnings=len(proposal.warnings),
        cost_usd=round(result.cost_usd, 6),
    )
    return proposal
