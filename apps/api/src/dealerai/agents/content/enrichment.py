"""Vehicle enrichment: normalise names, fill blank specs, extract selling points.

Runs once per vehicle, on `vehicle.created`. See docs/05-workflows.md § W2.

This is the module most able to embarrass a dealer, because everything it writes
is later stated as fact — in a post, in an ad, in a reply to a customer who then
turns up expecting 400 horsepower.

So it does not trust the model with a fact. The model proposes a value together
with the sentence it read that value in; this module checks the sentence really
appears in the text the model was shown, and drops the proposal if it does not.
A field left null shows in the dealer's screen as incomplete and gets filled in
by a human. An invented figure is not visible at all until it is too late.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

import structlog
from pydantic import BaseModel, Field

from ...ai.gateway import SystemLayers, complete
from ...ai.models import TaskKind
from ...ai.prompts import load
from ...db.session import tenant_session

log = structlog.get_logger()

#: The only columns a document is allowed to fill, with the type they parse to.
#:
#: Everything absent from this table is absent deliberately. `price_minor` and
#: `min_price_minor` are not here because a price list in the tenant's library
#: would otherwise be a back door around POST /v1/vehicles/{id}/price — the
#: endpoint that writes price history and warns already-published content. And
#: `mileage_km`, `vin` and `stock_number` describe one individual car, which a
#: document about a model cannot possibly know.
ENRICHABLE: dict[str, type[int] | type[str]] = {
    "body_type": str,
    "engine": str,
    "transmission": str,
    "drivetrain": str,
    "fuel": str,
    "power_hp": int,
    "torque_nm": int,
    "seats": int,
}

EnrichableField = Literal[
    "body_type", "engine", "transmission", "drivetrain", "fuel", "power_hp", "torque_nm", "seats"
]

#: A quote shorter than this matches half the document by accident. "5" appears
#: in every spec sheet ever written; "Seating capacity: 5" does not.
MIN_QUOTE_CHARS = 12

MAX_DOC_CHARS = 12_000
MAX_DOCS = 3
MAX_USPS = 5


class SpecFill(BaseModel):
    field: EnrichableField
    value: str = Field(description="The value, converted to metric. Numbers as digits only.")
    quote: str = Field(
        description="The sentence or table row this came from, copied verbatim from the document."
    )


class USP(BaseModel):
    text: str = Field(max_length=140, description="One short selling point.")
    basis: str = Field(description="The vehicle field it is grounded in, e.g. 'mileage_km'.")


class Enrichment(BaseModel):
    make: str = Field(min_length=1, max_length=60)
    model: str = Field(min_length=1, max_length=60)
    trim: str | None = None
    fills: list[SpecFill] = Field(default_factory=list)
    usps: list[USP] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Verified:
    """What survived checking.

    `dropped` is kept and logged rather than discarded — it is the only record
    of what the model tried to get away with, and the first thing worth reading
    when a prompt change makes enrichment quietly stop filling anything.
    """

    updates: dict[str, Any]
    usps: list[USP]
    provenance: list[dict[str, Any]]
    dropped: list[str]


def _squash(text: str) -> str:
    """Whitespace- and case-insensitive form, for substring comparison.

    A table row extracted from a PDF arrives with runs of spaces and stray
    newlines that the model tidies as it quotes. Comparing squashed forms
    tolerates that without tolerating a paraphrase.
    """
    return " ".join(text.split()).casefold()


def _words(name: str) -> list[str]:
    return [w for w in "".join(c if c.isalnum() else " " for c in name).casefold().split() if w]


def _normalisation_ok(before: str, after: str) -> bool:
    """Normalising a name may re-case and re-punctuate it. It may not rewrite it.

    Without this, "X5" comes back as "X5 xDrive40i" and the model has invented a
    trim level that the dealer never typed and no document mentions.

    A non-ASCII original is exempt: a make written in Arabic shares no words
    with its Latin spelling, and transliterating it is the entire point.
    """
    return not before.isascii() or _words(before) == _words(after)


def _parse(field: str, raw: str) -> Any:
    if ENRICHABLE[field] is int:
        digits = "".join(c for c in raw if c.isdigit())
        return int(digits) if digits else None
    return raw.strip() or None


def verify(proposal: Enrichment, *, record: dict[str, Any], documents: str) -> Verified:
    """Keep only what is provably grounded.

    Pure, so every rule below is testable without spending money on a model
    call — and so the rules are the same whatever the model returns.
    """
    haystack = _squash(documents)
    updates: dict[str, Any] = {}
    provenance: list[dict[str, Any]] = []
    dropped: list[str] = []

    for name in ("make", "model", "trim"):
        before, after = record.get(name), getattr(proposal, name)
        if not after or not before or after == before:
            continue
        if _normalisation_ok(str(before), after):
            updates[name] = after
        else:
            dropped.append(f"{name}: rewritten, not normalised ({before!r} -> {after!r})")

    for fill in proposal.fills:
        # Enrichment fills gaps. A value already in the record was put there by
        # the dealer or their DMS, and beats anything read out of a PDF.
        if record.get(fill.field) is not None:
            dropped.append(f"{fill.field}: already set")
            continue
        quote = _squash(fill.quote)
        if len(quote) < MIN_QUOTE_CHARS or quote not in haystack:
            dropped.append(f"{fill.field}: quote not found in the documents")
            continue
        if _squash(fill.value) not in quote:
            # The quote is real but says nothing about this value — a genuine
            # sentence about torque, reused to justify a horsepower figure.
            dropped.append(f"{fill.field}: value {fill.value!r} is not in its own quote")
            continue
        value = _parse(fill.field, fill.value)
        if value is None:
            dropped.append(f"{fill.field}: unparseable value {fill.value!r}")
            continue
        updates[fill.field] = value
        provenance.append({"field": fill.field, "value": value, "quote": fill.quote.strip()})

    merged = {**record, **updates}
    usps: list[USP] = []
    for usp in proposal.usps:
        if not merged.get(usp.basis):
            dropped.append(f"usp: basis {usp.basis!r} is blank on this vehicle")
            continue
        usps.append(usp)

    return Verified(updates=updates, usps=usps[:MAX_USPS], provenance=provenance, dropped=dropped)


_DOCS_SQL = """
select id, title, left(content, $3) as content
  from documents
 where tenant_id = $1
   and kind = 'spec_sheet'
   and status = 'ready'
   and content is not null
   and position(lower($2) in lower(content)) > 0
 order by length(content)
 limit $4
"""


async def _documents(tenant_id: UUID, model: str) -> tuple[str, list[UUID]]:
    """The tenant's spec sheets that mention this model.

    Matched on model, not make: a dealer's Toyota folder matches every sheet
    they own, while "Land Cruiser" matches the ones that could actually say
    something. `position()` rather than `ilike` because a model name is user
    data and `%` and `_` are pattern characters.

    No embeddings. A substring match over a handful of documents is what this
    needs today, and doing it properly would mean an ANN index that nothing
    populates yet.
    """
    async with tenant_session(tenant_id) as conn:
        rows = await conn.fetch(_DOCS_SQL, tenant_id, model, MAX_DOC_CHARS, MAX_DOCS)
    if not rows:
        return "", []
    body = "\n\n".join(f"### {r['title'] or 'Untitled'}\n{r['content']}" for r in rows)
    return f"<untrusted>\n{body}\n</untrusted>", [r["id"] for r in rows]


def _describe(record: dict[str, Any]) -> tuple[str, list[str]]:
    known = {
        k: v
        for k, v in record.items()
        if v not in (None, "", [], {}) and k not in ("id", "min_price_minor")
    }
    blank = sorted(f for f in ENRICHABLE if record.get(f) is None)
    return "\n".join(f"{k}: {v}" for k, v in sorted(known.items())), blank


_SELECT = """
select id, make, model, trim, model_year, body_type, vehicle_condition, mileage_km,
       engine, power_hp, torque_nm, transmission, drivetrain, fuel,
       exterior_color, interior_color, seats, features, specs, price_minor, currency
  from vehicles where id = $1
"""


async def enrich(*, tenant_id: UUID, vehicle_id: UUID, run_id: UUID | None = None) -> Verified:
    """Enrich one vehicle in place. Returns what was written."""
    async with tenant_session(tenant_id) as conn:
        row = await conn.fetchrow(_SELECT, vehicle_id)
    if row is None:
        raise ValueError(f"no such vehicle {vehicle_id}")
    record = dict(row)

    documents, document_ids = await _documents(tenant_id, record["model"])
    known, blank = _describe(record)

    result = await complete(
        TaskKind.ENRICHMENT,
        tenant_id=tenant_id,
        system=SystemLayers(role=load("enrichment")),
        messages=(
            f"## Vehicle record\n{known}\n\n"
            f"## Blank fields you may fill\n{', '.join(blank) or 'none'}\n\n"
            f"## Specification documents\n{documents or 'None supplied.'}"
        ),
        output_schema=Enrichment,
        run_id=run_id,
        trace_name="enrichment",
    )
    assert isinstance(result.parsed, Enrichment)  # noqa: S101 - schema-constrained
    verified = verify(result.parsed, record=record, documents=documents)
    await _write(tenant_id, vehicle_id, verified, document_ids)

    log.info(
        "vehicle_enriched",
        vehicle_id=str(vehicle_id),
        filled=sorted(verified.updates),
        usps=len(verified.usps),
        dropped=verified.dropped,
    )
    return verified


async def _write(
    tenant_id: UUID, vehicle_id: UUID, verified: Verified, document_ids: list[UUID]
) -> None:
    specs = {
        "usps": [u.model_dump() for u in verified.usps],
        "enrichment": {
            "at": datetime.now(UTC).isoformat(),
            "sources": [str(d) for d in document_ids],
            "filled": verified.provenance,
        },
    }
    # Column names come from ENRICHABLE and the three name fields, never from
    # model output — which is why EnrichableField is a Literal and not a str.
    assignments = "".join(f", {name} = ${i + 3}" for i, name in enumerate(verified.updates))
    async with tenant_session(tenant_id) as conn:
        await conn.execute(
            f"update vehicles set specs = specs || $2::jsonb{assignments} where id = $1",  # noqa: S608
            vehicle_id,
            specs,
            *verified.updates.values(),
        )
