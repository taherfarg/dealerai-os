"""Inbound: where a bought car is, what papers it still needs, what it cost to
bring in. docs/lifecycle/README.md § L4.

Where a car is and when it lands is everybody's: a salesperson promising a
customer a date needs it. The papers and the landed cost are the buy side —
answered only on a session cleared for `costs.view`, and behind the wall in
Postgres (0019_lifecycle_inbound.sql). `inbound.edit` (owner, admin, manager)
moves the journey along.

Reading a shipping document is a proposal: `/inbound/read` returns what the
paper says and whether it is this car's, and writes nothing but the file;
`/inbound/confirm` applies what the person posted back.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

import asyncpg
import structlog
from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel, Field

from ..core.errors import NotFound, Unusable
from ..deps import Ctx, TenantContext, require_permission
from ..lifecycle import inbound, invoices
from ..media import storage
from ..sales.clock import zone
from .acquisition import _session, _vehicle

log = structlog.get_logger()

router = APIRouter(prefix="/v1/vehicles", tags=["inbound"])

Editor = Annotated[TenantContext, Depends(require_permission("inbound.edit"))]

MilestoneCode = Literal[
    "purchased",
    "paid",
    "picked_up",
    "at_origin_port",
    "departed",
    "arrived_port",
    "customs_cleared",
    "delivered",
    "collected",
    "registered",
]
PaperCode = Literal[
    "bill_of_sale",
    "title",
    "bill_of_lading",
    "customs_declaration",
    "customs_certificate",
    "registration_card",
]

_FIELDS = (
    "origin_country",
    "carrier",
    "reference",
    "vessel",
    "container",
    "port_of_loading",
    "port_of_discharge",
    "eta",
)


class Journey(BaseModel):
    route: inbound.Route | None = None
    origin_country: str | None = Field(default=None, min_length=2, max_length=2)
    carrier: str | None = Field(default=None, max_length=120)
    reference: str | None = Field(default=None, max_length=120)
    vessel: str | None = Field(default=None, max_length=120)
    container: str | None = Field(default=None, max_length=40)
    port_of_loading: str | None = Field(default=None, max_length=120)
    port_of_discharge: str | None = Field(default=None, max_length=120)
    eta: date | None = None


class MilestoneIn(BaseModel):
    status: Literal["pending", "done", "skipped"]
    #: When it happened. Today when left out.
    done_on: date | None = None
    expected_on: date | None = None
    note: str | None = Field(default=None, max_length=500)


class PaperIn(BaseModel):
    status: Literal["missing", "received", "not_needed"]


class Step(BaseModel):
    code: MilestoneCode
    done_on: date | None = None


class Paper(BaseModel):
    code: PaperCode
    document_path: str = Field(max_length=500)


class Confirmation(BaseModel):
    """What a person accepted from a reading, in one transaction."""

    journey: Journey = Field(default_factory=Journey)
    milestone: Step | None = None
    paper: Paper | None = None


class MilestoneOut(BaseModel):
    code: str
    status: str
    expected_on: date | None
    done_on: date | None
    note: str | None


class PaperOut(BaseModel):
    code: str
    status: str
    document_path: str | None
    received_on: date | None


class MissingOut(BaseModel):
    documents: list[str]
    costs: list[str]
    estimated: list[str]
    complete: bool


class InboundOut(BaseModel):
    vehicle_id: UUID
    started: bool
    route: str | None
    origin_country: str | None
    carrier: str | None
    reference: str | None
    vessel: str | None
    container: str | None
    port_of_loading: str | None
    port_of_discharge: str | None
    eta: date | None
    arrived_at: datetime | None
    #: The next step after the furthest one reached; null once on the lot.
    stage: str | None
    #: Past its ETA and not on the lot.
    late: bool
    milestones: list[MilestoneOut]
    #: The buy side: null for anyone not cleared to see it.
    documents: list[PaperOut] | None
    missing: MissingOut | None


class ShippingOut(BaseModel):
    kind: str
    reference: str | None
    carrier: str | None
    vessel: str | None
    container: str | None
    port_of_loading: str | None
    port_of_discharge: str | None
    departed_on: date | None
    eta: date | None
    vins: list[str]
    #: This car's VIN is on the document. Nothing should be applied otherwise.
    matches: bool
    milestone: str | None
    paper: str | None
    warnings: list[str]
    document_path: str | None


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


async def _today(conn: asyncpg.Connection, tenant_id: UUID) -> date:
    timezone = await conn.fetchval("select timezone from tenants where id = $1", tenant_id)
    return datetime.now(zone(timezone)).date()


async def _journey(
    conn: asyncpg.Connection, ctx: TenantContext, vehicle_id: UUID
) -> dict[str, Any]:
    row = await conn.fetchrow("select * from vehicle_inbound where vehicle_id = $1", vehicle_id)
    milestones = await conn.fetch(
        """select code, status, expected_on, done_on, note from inbound_milestones
            where vehicle_id = $1 order by position""",
        vehicle_id,
    )
    cleared = ctx.may("costs.view")
    documents = None
    missing = None
    if cleared and row is not None:
        documents = [
            dict(r)
            for r in await conn.fetch(
                """select code, status, document_path, received_on from inbound_documents
                    where vehicle_id = $1 order by position""",
                vehicle_id,
            )
        ]
        found = await inbound.missing(conn, vehicle_id)
        if found is not None:
            missing = {
                "documents": found.documents,
                "costs": found.costs,
                "estimated": found.estimated,
                "complete": found.nothing,
            }
    today = await _today(conn, ctx.tenant_id)
    # Where the car is: the step after the furthest one reached. A car at sea
    # has been paid for whether or not anybody ticked it.
    furthest = max((i for i, m in enumerate(milestones) if m["status"] != "pending"), default=-1)
    stage = next((m["code"] for m in milestones[furthest + 1 :] if m["status"] == "pending"), None)
    arrived = row is not None and row["arrived_at"] is not None
    return {
        "vehicle_id": vehicle_id,
        "started": row is not None,
        "route": row["route"] if row else None,
        **{name: (row[name] if row else None) for name in _FIELDS},
        "arrived_at": row["arrived_at"] if row else None,
        "stage": None if arrived else stage,
        "late": bool(row and not arrived and row["eta"] and row["eta"] < today),
        "milestones": [dict(m) for m in milestones],
        "documents": documents,
        "missing": missing,
    }


async def _apply_journey(
    conn: asyncpg.Connection, ctx: TenantContext, vehicle_id: UUID, journey: Journey
) -> None:
    changes = journey.model_dump(exclude_unset=True)
    route = changes.pop("route", None)
    exists = await conn.fetchval(
        "select route from vehicle_inbound where vehicle_id = $1", vehicle_id
    )
    if route is not None and route != exists:
        await inbound.start(conn, ctx.tenant_id, vehicle_id, route)
    elif exists is None:
        raise Unusable(
            "say whether the car is an import or a local purchase first",
            ar="حدّد أولًا إن كانت السيارة مستوردة أو مشتراة محليًا.",
        )
    for name, value in changes.items():
        if name == "origin_country" and value:
            value = value.upper()
        await conn.execute(
            f"update vehicle_inbound set {name} = $2 where vehicle_id = $1",  # noqa: S608
            vehicle_id,
            value,
        )


def _path_ok(ctx: TenantContext, path: str) -> None:
    """Input from the browser: this tenant's, and a paper or an invoice."""
    if not path.startswith((f"{ctx.tenant_id}/inbound/", f"{ctx.tenant_id}/invoices/")):
        raise Unusable(
            "that document is not one of this dealership's",
            ar="هذا المستند ليس من مستندات هذا المعرض.",
        )


async def _mark(
    conn: asyncpg.Connection, ctx: TenantContext, vehicle_id: UUID, code: str, body: MilestoneIn
) -> None:
    moved = await inbound.mark(
        conn,
        ctx.tenant_id,
        vehicle_id,
        code,
        status=body.status,
        done_on=body.done_on,
        expected_on=body.expected_on,
        note=body.note,
    )
    if not moved:
        raise NotFound(
            "this car's journey has no such step", ar="لا توجد هذه المرحلة في رحلة السيارة."
        )


async def _receive(conn: asyncpg.Connection, vehicle_id: UUID, code: str, path: str | None) -> None:
    updated = await conn.fetchval(
        """update inbound_documents
              set status = 'received', document_path = coalesce($3, document_path),
                  received_on = current_date
            where vehicle_id = $1 and code = $2 returning code""",
        vehicle_id,
        code,
        path,
    )
    if updated is None:
        raise NotFound("this car needs no such paper", ar="هذه السيارة لا تحتاج هذا المستند.")


async def _upload(ctx: TenantContext, file: UploadFile) -> tuple[bytes, str, str]:
    mime = (file.content_type or "").split(";")[0].strip().lower()
    if mime not in invoices.MIME_TYPES:
        raise Unusable(
            "a document is a photograph (JPEG, PNG, WebP) or a PDF",
            ar="المستند يكون صورة (JPEG أو PNG أو WebP) أو ملف PDF.",
        )
    data = await file.read()
    if not data or len(data) > invoices.MAX_BYTES:
        raise Unusable(
            "a document must be under 15 MB and not empty",
            ar="المستند يجب ألا يكون فارغًا وأن يكون أصغر من ١٥ ميجابايت.",
        )
    path = storage.object_path(ctx.tenant_id, "inbound", storage.extension_for(mime, file.filename))
    return data, mime, path


# --------------------------------------------------------------------------
# the journey
# --------------------------------------------------------------------------


@router.get("/{vehicle_id}/inbound", response_model=InboundOut)
async def get_inbound(vehicle_id: UUID, ctx: Ctx) -> dict[str, Any]:
    async with _session(ctx) as conn:
        await _vehicle(conn, vehicle_id)
        return await _journey(conn, ctx, vehicle_id)


@router.patch("/{vehicle_id}/inbound", response_model=InboundOut)
async def patch_inbound(vehicle_id: UUID, body: Journey, ctx: Editor) -> dict[str, Any]:
    """Start a journey (route), change it, or correct its details."""
    async with _session(ctx) as conn, conn.transaction():
        await _vehicle(conn, vehicle_id)
        await _apply_journey(conn, ctx, vehicle_id, body)
        return await _journey(conn, ctx, vehicle_id)


@router.post("/{vehicle_id}/inbound/milestones/{code}", response_model=InboundOut)
async def move_milestone(
    vehicle_id: UUID, code: MilestoneCode, body: MilestoneIn, ctx: Editor
) -> dict[str, Any]:
    async with _session(ctx) as conn, conn.transaction():
        await _vehicle(conn, vehicle_id)
        await _mark(conn, ctx, vehicle_id, code, body)
        return await _journey(conn, ctx, vehicle_id)


@router.patch("/{vehicle_id}/inbound/documents/{code}", response_model=InboundOut)
async def set_paper(
    vehicle_id: UUID, code: PaperCode, body: PaperIn, ctx: Editor
) -> dict[str, Any]:
    """Received on paper, not needed for this car, or missing after all."""
    async with _session(ctx) as conn, conn.transaction():
        await _vehicle(conn, vehicle_id)
        if body.status == "received":
            await _receive(conn, vehicle_id, code, None)
        elif not await conn.fetchval(
            """update inbound_documents set status = $3, received_on = null
                where vehicle_id = $1 and code = $2 returning code""",
            vehicle_id,
            code,
            body.status,
        ):
            raise NotFound("this car needs no such paper", ar="هذه السيارة لا تحتاج هذا المستند.")
        return await _journey(conn, ctx, vehicle_id)


@router.post("/{vehicle_id}/inbound/documents/{code}/file", response_model=InboundOut)
async def upload_paper(
    vehicle_id: UUID, code: PaperCode, ctx: Editor, file: Annotated[UploadFile, File()]
) -> dict[str, Any]:
    data, mime, path = await _upload(ctx, file)
    async with _session(ctx) as conn:
        await _vehicle(conn, vehicle_id)
        if not await conn.fetchval(
            "select 1 from inbound_documents where vehicle_id = $1 and code = $2", vehicle_id, code
        ):
            raise NotFound("this car needs no such paper", ar="هذه السيارة لا تحتاج هذا المستند.")
    await storage.upload(path, data, content_type=mime)
    async with _session(ctx) as conn, conn.transaction():
        await _receive(conn, vehicle_id, code, path)
        return await _journey(conn, ctx, vehicle_id)


# --------------------------------------------------------------------------
# reading a shipping document
# --------------------------------------------------------------------------


@router.post("/{vehicle_id}/inbound/read", response_model=ShippingOut)
async def read_shipping(
    vehicle_id: UUID, ctx: Editor, file: Annotated[UploadFile, File()]
) -> dict[str, Any]:
    """What a shipping document says, and whether it is this car's. Applies nothing."""
    data, mime, path = await _upload(ctx, file)
    async with _session(ctx) as conn:
        car = await conn.fetchrow("select vin from vehicles where id = $1", vehicle_id)
        if car is None:
            raise NotFound("no such vehicle", ar="لا توجد سيارة بهذا الرقم.")
        today = await _today(conn, ctx.tenant_id)

    proposal = await inbound.read(
        tenant_id=ctx.tenant_id, data=data, mime_type=mime, car_vin=car["vin"], today=today
    )
    document_path: str | None = path
    try:
        await storage.upload(path, data, content_type=mime)
    except Exception as exc:  # noqa: BLE001 - the reading is still worth showing
        log.warning("shipping_document_not_stored", error=str(exc))
        proposal.warnings.append("the document could not be kept; the reading is still usable")
        document_path = None
    return {
        "kind": proposal.kind,
        "reference": proposal.reference,
        "carrier": proposal.carrier,
        "vessel": proposal.vessel,
        "container": proposal.container,
        "port_of_loading": proposal.port_of_loading,
        "port_of_discharge": proposal.port_of_discharge,
        "departed_on": proposal.departed_on,
        "eta": proposal.eta,
        "vins": proposal.vins,
        "matches": proposal.matches,
        "milestone": proposal.milestone,
        "paper": proposal.paper,
        "warnings": proposal.warnings,
        "document_path": document_path,
    }


@router.post("/{vehicle_id}/inbound/confirm", response_model=InboundOut)
async def confirm_reading(vehicle_id: UUID, body: Confirmation, ctx: Editor) -> dict[str, Any]:
    """Apply what a person accepted from a reading: the details, the step it
    proves, the paper it is. All of it or none of it."""
    if body.paper is not None:
        _path_ok(ctx, body.paper.document_path)
    async with _session(ctx) as conn, conn.transaction():
        await _vehicle(conn, vehicle_id)
        await _apply_journey(conn, ctx, vehicle_id, body.journey)
        if body.milestone is not None:
            await _mark(
                conn,
                ctx,
                vehicle_id,
                body.milestone.code,
                MilestoneIn(status="done", done_on=body.milestone.done_on),
            )
        if body.paper is not None:
            await _receive(conn, vehicle_id, body.paper.code, body.paper.document_path)
        return await _journey(conn, ctx, vehicle_id)
