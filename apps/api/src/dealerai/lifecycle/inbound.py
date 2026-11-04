"""Getting a bought car to the lot: where it is, what is missing, what it cost.

A car bought at a US auction is towed to a port, loaded, shipped, cleared and
delivered — weeks, five companies and a stack of paper. Each car carries a
journey of milestones and a checklist of papers chosen by its route, and the
landed cost is checked against the fees that route always has. The slice's
exit criterion: **a US-auction car shows where it is and what is missing, and
its landed cost is complete the day it arrives.**

Where the AI is: reading a shipping document — a bill of lading, an arrival
notice, a customs declaration — into the journey's fields. What it is not
trusted with is which car the paper is for. The model is not told the VIN; it
lists the VINs it reads, each with the line it read it from, and code decides
whether this car's is among them. A bill of lading for the wrong car, applied,
is a car marked shipped that is still standing in Texas.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Literal
from uuid import UUID

import asyncpg
import structlog
from google.genai import types
from pydantic import BaseModel, Field

from ..ai.gateway import SystemLayers, complete
from ..ai.models import TaskKind
from ..ai.prompts import load
from ..events.bus import emit

log = structlog.get_logger()

Route = Literal["import", "local"]

#: The journey, in order. A local car is collected; an import is delivered.
MILESTONES: dict[str, tuple[str, ...]] = {
    "import": (
        "purchased",
        "paid",
        "picked_up",
        "at_origin_port",
        "departed",
        "arrived_port",
        "customs_cleared",
        "delivered",
        "registered",
    ),
    "local": ("purchased", "paid", "collected", "registered"),
}
#: The milestone that means "it is on our lot".
ARRIVAL: dict[str, str] = {"import": "delivered", "local": "collected"}

#: The papers a car arrives with: what a UAE import and a local purchase carry.
#: The title is a used car's (a US auction's, typically); a new car has none —
#: Pollux sells new cars (docs/lifecycle/pollux.md), so it is left off theirs.
DOCUMENTS: dict[str, tuple[str, ...]] = {
    "import": (
        "bill_of_sale",
        "title",
        "bill_of_lading",
        "customs_declaration",
        "customs_certificate",
    ),
    "local": ("bill_of_sale", "registration_card"),
}


def expected_costs(route: str, source: str | None) -> list[str]:
    """The ledger categories a car on this route always has. An auction car
    has the auction's fees; every import has been towed, shipped and cleared."""
    categories = ["purchase"]
    if source == "auction":
        categories.append("auction_fee")
    if route == "import":
        categories += ["transport", "shipping", "customs"]
    return categories


# --------------------------------------------------------------------------
# the journey
# --------------------------------------------------------------------------


async def start(conn: asyncpg.Connection, tenant_id: UUID, vehicle_id: UUID, route: Route) -> None:
    """Begin a car's journey, or change its route. Milestones and papers the
    two routes share keep what was recorded; the rest are added or removed."""
    await conn.execute(
        """insert into vehicle_inbound (vehicle_id, tenant_id, route) values ($1, $2, $3)
           on conflict (vehicle_id) do update set route = excluded.route""",
        vehicle_id,
        tenant_id,
        route,
    )
    milestones = MILESTONES[route]
    await conn.execute(
        "delete from inbound_milestones where vehicle_id = $1 and code <> all($2::text[])",
        vehicle_id,
        list(milestones),
    )
    purchased_on = await conn.fetchval(
        "select purchased_at from vehicle_acquisitions where vehicle_id = $1", vehicle_id
    )
    for position, code in enumerate(milestones):
        done = code == "purchased" and purchased_on is not None
        await conn.execute(
            """insert into inbound_milestones
                 (vehicle_id, tenant_id, code, position, status, done_on)
               values ($1, $2, $3, $4, $5, $6)
               on conflict (vehicle_id, code) do update set position = excluded.position""",
            vehicle_id,
            tenant_id,
            code,
            position,
            "done" if done else "pending",
            purchased_on if done else None,
        )
    condition = await conn.fetchval(
        "select vehicle_condition from vehicles where id = $1", vehicle_id
    )
    documents = tuple(
        code for code in DOCUMENTS[route] if not (code == "title" and condition == "new")
    )
    await conn.execute(
        "delete from inbound_documents where vehicle_id = $1 and code <> all($2::text[])",
        vehicle_id,
        list(documents),
    )
    for position, code in enumerate(documents):
        await conn.execute(
            """insert into inbound_documents (vehicle_id, tenant_id, code, position)
               values ($1, $2, $3, $4)
               on conflict (vehicle_id, code) do update set position = excluded.position""",
            vehicle_id,
            tenant_id,
            code,
            position,
        )


async def mark(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    vehicle_id: UUID,
    code: str,
    *,
    status: Literal["pending", "done", "skipped"],
    done_on: date | None = None,
    expected_on: date | None = None,
    note: str | None = None,
) -> bool:
    """Move one milestone. Reaching the lot records the arrival and emits
    `inbound.arrived`, once. Returns False when the car has no such milestone."""
    route = await conn.fetchval(
        "select route from vehicle_inbound where vehicle_id = $1 for update", vehicle_id
    )
    if route is None:
        return False
    updated = await conn.fetchval(
        """update inbound_milestones
              set status = $3,
                  done_on = case when $3 = 'done' then coalesce($4, current_date) end,
                  expected_on = coalesce($5, expected_on),
                  note = coalesce($6, note)
            where vehicle_id = $1 and code = $2
        returning code""",
        vehicle_id,
        code,
        status,
        done_on,
        expected_on,
        note,
    )
    if updated is None:
        return False
    if code == ARRIVAL[route]:
        if status == "done":
            arrived = await conn.fetchval(
                """update vehicle_inbound set arrived_at = now()
                    where vehicle_id = $1 and arrived_at is null returning vehicle_id""",
                vehicle_id,
            )
            if arrived:
                await emit(
                    conn,
                    "inbound.arrived",
                    {"vehicle_id": str(vehicle_id)},
                    tenant_id=tenant_id,
                    dedupe_key=f"inbound.arrived:{vehicle_id}",
                )
        else:
            await conn.execute(
                "update vehicle_inbound set arrived_at = null where vehicle_id = $1", vehicle_id
            )
    return True


@dataclass(frozen=True, slots=True)
class Missing:
    """What stands between a car and a complete record."""

    documents: list[str]
    #: Categories the route always has and the ledger has nothing actual for.
    costs: list[str]
    #: Of those the ledger has, the ones that are still only estimates.
    estimated: list[str]

    @property
    def nothing(self) -> bool:
        return not (self.documents or self.costs or self.estimated)


async def missing(conn: asyncpg.Connection, vehicle_id: UUID) -> Missing | None:
    """Papers not received and fees not recorded — through the buy-side wall,
    so only on a session cleared for it. None when the car has no journey."""
    row = await conn.fetchrow(
        """select i.route, a.source from vehicle_inbound i
             left join vehicle_acquisitions a on a.vehicle_id = i.vehicle_id
            where i.vehicle_id = $1""",
        vehicle_id,
    )
    if row is None:
        return None
    documents = [
        r["code"]
        for r in await conn.fetch(
            """select code from inbound_documents
                where vehicle_id = $1 and status = 'missing' order by position""",
            vehicle_id,
        )
    ]
    lines = await conn.fetch(
        "select category, status from vehicle_costs where vehicle_id = $1", vehicle_id
    )
    actual = {line["category"] for line in lines if line["status"] == "actual"}
    estimated = {line["category"] for line in lines if line["status"] == "estimate"}
    expected = expected_costs(row["route"], row["source"])
    return Missing(
        documents=documents,
        costs=[c for c in expected if c not in actual and c not in estimated],
        estimated=[c for c in expected if c not in actual and c in estimated],
    )


async def late(conn: asyncpg.Connection, tenant_id: UUID, today: date) -> list[UUID]:
    """Cars whose ETA has passed and that are not on the lot."""
    rows = await conn.fetch(
        """select vehicle_id from vehicle_inbound
            where tenant_id = $1 and arrived_at is null and eta < $2
            order by eta""",
        tenant_id,
        today,
    )
    return [row["vehicle_id"] for row in rows]


# --------------------------------------------------------------------------
# reading a shipping document
# --------------------------------------------------------------------------

DocumentKind = Literal[
    "bill_of_lading", "booking_confirmation", "arrival_notice", "customs_declaration", "other"
]

#: What a document of each kind proves happened, and which paper it is.
PROVES: dict[str, str] = {
    "bill_of_lading": "departed",
    "arrival_notice": "arrived_port",
    "customs_declaration": "customs_cleared",
}
IS_PAPER: dict[str, str] = {
    "bill_of_lading": "bill_of_lading",
    "customs_declaration": "customs_declaration",
}


class SeenVin(BaseModel):
    vin: str = Field(description="The VIN exactly as printed.")
    quote: str = Field(max_length=300, description="The printed line the VIN is on.")


class ShippingReading(BaseModel):
    """Text as printed; code decides what it proves."""

    kind: DocumentKind
    reference: str | None = Field(
        default=None, max_length=120, description="Bill of lading, booking or declaration number."
    )
    reference_quote: str | None = Field(default=None, max_length=300)
    carrier: str | None = Field(default=None, max_length=120)
    vessel: str | None = Field(default=None, max_length=120)
    container: str | None = Field(default=None, max_length=40)
    port_of_loading: str | None = Field(default=None, max_length=120)
    port_of_discharge: str | None = Field(default=None, max_length=120)
    departed_on: str | None = Field(default=None, description="YYYY-MM-DD, if printed.")
    eta: str | None = Field(default=None, description="Estimated arrival, YYYY-MM-DD, if printed.")
    vins: list[SeenVin] = Field(default_factory=list)


_VIN = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")


def normal_vin(raw: str) -> str:
    return re.sub(r"[\s-]", "", raw).upper()


def _date(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw.strip()[:10])
    except ValueError:
        return None


@dataclass(slots=True)
class ShippingProposal:
    kind: str
    reference: str | None
    carrier: str | None
    vessel: str | None
    container: str | None
    port_of_loading: str | None
    port_of_discharge: str | None
    departed_on: date | None
    eta: date | None
    #: Every VIN that is well formed and found in its own line.
    vins: list[str]
    #: True only when this car's VIN is one of them. Nothing is applied otherwise.
    matches: bool
    milestone: str | None
    paper: str | None
    warnings: list[str] = field(default_factory=list)


def verify(reading: ShippingReading, *, car_vin: str | None, today: date) -> ShippingProposal:
    """Keep what is on the paper; decide whether the paper is this car's.

    Pure, so the rule holds whatever the model returns: a VIN counts only when
    it is a VIN (17 characters, no I, O or Q) and appears in the line it was
    read from, and the document is this car's only when this car's VIN is
    among those.
    """
    warnings: list[str] = []
    vins: list[str] = []
    for seen in reading.vins:
        vin = normal_vin(seen.vin)
        if not _VIN.match(vin):
            warnings.append(f"{seen.vin!r} is not a VIN")
            continue
        if vin not in normal_vin(seen.quote):
            warnings.append(f"{vin} does not appear in the line it was read from")
            continue
        if vin not in vins:
            vins.append(vin)

    ours = normal_vin(car_vin) if car_vin else None
    matches = ours is not None and ours in vins
    if ours is None:
        warnings.append("this car has no VIN recorded, so the document cannot be matched to it")
    elif not matches:
        warnings.append(
            f"this car's VIN {ours} is not on the document"
            + (f" (it names {', '.join(vins)})" if vins else "")
        )

    reference = (reading.reference or "").strip() or None
    if reference and reading.reference_quote and reference not in reading.reference_quote:
        warnings.append(f"the reference {reference} does not appear where it was read")
        reference = None

    departed_on = _date(reading.departed_on)
    if departed_on and departed_on > today:
        # A sailing date in the future is a schedule, not a departure.
        warnings.append(f"the departure date {departed_on} has not happened yet")
    milestone = PROVES.get(reading.kind)
    if milestone == "departed" and (departed_on is None or departed_on > today):
        milestone = None

    def text(value: str | None) -> str | None:
        return (value or "").strip() or None

    return ShippingProposal(
        kind=reading.kind,
        reference=reference,
        carrier=text(reading.carrier),
        vessel=text(reading.vessel),
        container=text(reading.container),
        port_of_loading=text(reading.port_of_loading),
        port_of_discharge=text(reading.port_of_discharge),
        departed_on=departed_on if departed_on and departed_on <= today else None,
        eta=_date(reading.eta),
        vins=vins,
        matches=matches,
        milestone=milestone,
        paper=IS_PAPER.get(reading.kind),
        warnings=warnings,
    )


async def read(
    *, tenant_id: UUID, data: bytes, mime_type: str, car_vin: str | None, today: date
) -> ShippingProposal:
    """Read one shipping document. One vision call; writes nothing. The VIN is
    not sent: the model reports the VINs it reads, and code compares."""
    turn = types.Content(
        role="user",
        parts=[
            types.Part.from_bytes(data=data, mime_type=mime_type),
            types.Part.from_text(text="Read this shipping document."),
        ],
    )
    result = await complete(
        TaskKind.VISION,
        tenant_id=tenant_id,
        system=SystemLayers(role=load("shipping_reader")),
        messages=turn,
        output_schema=ShippingReading,
        trace_name="shipping_reader",
    )
    assert isinstance(result.parsed, ShippingReading)  # noqa: S101 - schema-constrained
    proposal = verify(result.parsed, car_vin=car_vin, today=today)
    log.info(
        "shipping_document_read",
        kind=proposal.kind,
        vins=len(proposal.vins),
        matches=proposal.matches,
        warnings=len(proposal.warnings),
        cost_usd=round(result.cost_usd, 6),
    )
    return proposal
