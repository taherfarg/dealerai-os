"""The export file for an order: its procedure, the papers each step produced,
the commercial invoice, and the bill of lading draft check.
docs/lifecycle/README.md § L7.

`orders.edit` moves the procedure and keeps its papers — the salesperson who
talks to the buyer confirms the bill of lading draft with them. `orders.sign`
(owner, admin, manager) signs the commercial invoice: a document customs and a
buyer's bank act on is somebody's signature, not a button anybody can press.
"""

from __future__ import annotations

import mimetypes
from datetime import date, datetime
from pathlib import PurePosixPath
from typing import Annotated, Any, Literal
from uuid import UUID

import asyncpg
import structlog
from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..core.errors import NotFound, Unusable
from ..deps import Ctx, TenantContext, require_permission
from ..lifecycle import export, inbound, invoices
from ..media import storage
from ..sales.clock import zone
from .acquisition import _session

log = structlog.get_logger()

router = APIRouter(prefix="/v1", tags=["export"])

Seller = Annotated[TenantContext, Depends(require_permission("orders.edit"))]
Signer = Annotated[TenantContext, Depends(require_permission("orders.sign"))]

StepCode = Literal[
    "customer_documents",
    "assign_vehicle",
    "customs_card",
    "book_shipping",
    "export_inspection",
    "export_plates",
    "deliver_to_carrier",
    "export_certificate",
    "bl_draft_confirmed",
    "bl_original",
    "chamber_certificate",
    "commercial_invoice",
    "file_delivered",
    "rta_registration",
    "delivered",
]


class StepIn(BaseModel):
    status: Literal["pending", "done", "skipped"]
    done_on: date | None = None
    note: str | None = Field(default=None, max_length=500)


class Consignee(BaseModel):
    consignee_name: str | None = Field(default=None, max_length=200)
    consignee_address: str | None = Field(default=None, max_length=500)
    consignee_phone: str | None = Field(default=None, max_length=40)
    port_of_discharge: str | None = Field(default=None, max_length=120)
    shipping_method: Literal["container", "shared_container", "roro", "air"] | None = None


class StepOut(BaseModel):
    code: str
    status: str
    done_on: date | None
    note: str | None
    has_document: bool
    #: This step's paper is uploaded rather than drafted here.
    takes_document: bool


class ExportOut(BaseModel):
    order_id: UUID
    procedure: str
    #: The step after the furthest one reached; null when the file is complete.
    stage: str | None
    steps: list[StepOut]
    consignee_name: str | None
    consignee_address: str | None
    consignee_phone: str | None
    port_of_discharge: str | None
    shipping_method: str | None


class InvoiceOut(BaseModel):
    signed: bool
    signed_at: datetime | None
    signed_by: str | None
    document: dict[str, Any]
    #: What stops it being signed. Empty when it can be.
    problems: list[str]


class CheckOut(BaseModel):
    name: str
    ok: bool | None
    expected: str | None
    found: str | None


class DraftCheckOut(BaseModel):
    checks: list[CheckOut]
    #: Every check that could be made matches.
    clean: bool
    warnings: list[str]


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


async def _today(conn: asyncpg.Connection, tenant_id: UUID) -> date:
    return datetime.now(
        zone(await conn.fetchval("select timezone from tenants where id = $1", tenant_id))
    ).date()


async def _order_row(conn: asyncpg.Connection, order_id: UUID) -> asyncpg.Record:
    row = await conn.fetchrow("select * from sale_orders where id = $1", order_id)
    if row is None:
        raise NotFound("no such order", ar="لا يوجد طلب بهذا الرقم.")
    return row


async def _file(conn: asyncpg.Connection, order_id: UUID) -> dict[str, Any]:
    order = await _order_row(conn, order_id)
    steps = [
        dict(r)
        for r in await conn.fetch(
            """select code, status, done_on, note, document_path from order_steps
                where order_id = $1 order by position""",
            order_id,
        )
    ]
    return {
        "order_id": order_id,
        "procedure": export.procedure_for(order["purchase_type"], order["destination"]),
        "stage": export.stage(steps),
        "steps": [
            {
                "code": s["code"],
                "status": s["status"],
                "done_on": s["done_on"],
                "note": s["note"],
                "has_document": s["document_path"] is not None,
                "takes_document": s["code"] in export.PAPERS,
            }
            for s in steps
        ],
        **{
            name: order[name]
            for name in (
                "consignee_name",
                "consignee_address",
                "consignee_phone",
                "port_of_discharge",
                "shipping_method",
            )
        },
    }


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
    path = storage.object_path(ctx.tenant_id, "exports", storage.extension_for(mime, file.filename))
    return data, mime, path


# --------------------------------------------------------------------------
# the procedure
# --------------------------------------------------------------------------


@router.get("/orders/{order_id}/export", response_model=ExportOut)
async def get_export(order_id: UUID, ctx: Ctx) -> dict[str, Any]:
    async with _session(ctx) as conn:
        return await _file(conn, order_id)


@router.post("/orders/{order_id}/export/start", response_model=ExportOut)
async def start_export(order_id: UUID, ctx: Seller) -> dict[str, Any]:
    """Lay out the procedure for an order reserved before this existed. A
    deposit lays it out by itself."""
    async with _session(ctx) as conn, conn.transaction():
        order = await _order_row(conn, order_id)
        if order["status"] not in ("reserved", "completed"):
            raise Unusable(
                "the export file starts when a deposit reserves the car",
                ar="يبدأ ملف التصدير عندما يحجز العربون السيارة.",
            )
        await export.start(conn, ctx.tenant_id, order_id)
        return await _file(conn, order_id)


@router.patch("/orders/{order_id}/export", response_model=ExportOut)
async def set_consignee(order_id: UUID, body: Consignee, ctx: Seller) -> dict[str, Any]:
    """Who receives the car, where, and how it travels."""
    changes = body.model_dump(exclude_unset=True)
    async with _session(ctx) as conn, conn.transaction():
        order = await _order_row(conn, order_id)
        if order["invoice_number"] is not None and changes:
            raise Unusable(
                "the invoice is signed; what it says about the consignee stays as signed",
                ar="الفاتورة موقّعة، وبيانات المستلم فيها تبقى كما وُقّعت.",
            )
        for name, value in changes.items():
            await conn.execute(
                f"update sale_orders set {name} = $2 where id = $1",  # noqa: S608
                order_id,
                value.strip() if isinstance(value, str) else value,
            )
        return await _file(conn, order_id)


@router.post("/orders/{order_id}/export/steps/{code}", response_model=ExportOut)
async def move_step(order_id: UUID, code: StepCode, body: StepIn, ctx: Seller) -> dict[str, Any]:
    async with _session(ctx) as conn, conn.transaction():
        await _order_row(conn, order_id)
        if not await export.mark(
            conn, order_id, code, status=body.status, done_on=body.done_on, note=body.note
        ):
            raise NotFound(
                "this order's procedure has no such step",
                ar="لا توجد هذه الخطوة في إجراءات هذا الطلب.",
            )
        return await _file(conn, order_id)


@router.post("/orders/{order_id}/export/steps/{code}/document", response_model=ExportOut)
async def upload_step_document(
    order_id: UUID, code: StepCode, ctx: Seller, file: Annotated[UploadFile, File()]
) -> dict[str, Any]:
    if code not in export.PAPERS:
        raise Unusable(
            "this step's paper is drafted here, not uploaded",
            ar="مستند هذه الخطوة يُنشأ هنا ولا يُرفع.",
        )
    data, mime, path = await _upload(ctx, file)
    async with _session(ctx) as conn:
        await _order_row(conn, order_id)
        if not await conn.fetchval(
            "select 1 from order_steps where order_id = $1 and code = $2", order_id, code
        ):
            raise NotFound(
                "this order's procedure has no such step",
                ar="لا توجد هذه الخطوة في إجراءات هذا الطلب.",
            )
    await storage.upload(path, data, content_type=mime)
    async with _session(ctx) as conn, conn.transaction():
        await export.attach(conn, order_id, code, path)
        return await _file(conn, order_id)


@router.get("/orders/{order_id}/export/steps/{code}/document")
async def download_step_document(order_id: UUID, code: StepCode, ctx: Ctx) -> Response:
    """The paper a step produced, for the file the buyer is sent. The path is
    the one recorded on the step — never one the browser names."""
    async with _session(ctx) as conn:
        path = await conn.fetchval(
            "select document_path from order_steps where order_id = $1 and code = $2",
            order_id,
            code,
        )
    if not path:
        raise NotFound("no paper for this step yet", ar="لا يوجد مستند لهذه الخطوة بعد.")
    data = await storage.download(path)
    name = f"{code}{PurePosixPath(path).suffix}"
    return Response(
        content=data,
        media_type=mimetypes.guess_type(name)[0] or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


# --------------------------------------------------------------------------
# the commercial invoice
# --------------------------------------------------------------------------


@router.get("/orders/{order_id}/invoice", response_model=InvoiceOut)
async def get_invoice(order_id: UUID, ctx: Ctx) -> dict[str, Any]:
    """The signed invoice as signed, or the draft the record makes today."""
    async with _session(ctx) as conn:
        order = await _order_row(conn, order_id)
        document = await export.current_invoice(
            conn, ctx.tenant_id, order_id, today=await _today(conn, ctx.tenant_id)
        )
        signer = None
        if order["invoice_signed_by"] is not None:
            signer = await conn.fetchval(
                "select full_name from profiles where id = $1", order["invoice_signed_by"]
            )
    assert document is not None  # noqa: S101 - the order exists
    signed = order["invoice_number"] is not None
    return {
        "signed": signed,
        "signed_at": order["invoice_signed_at"],
        "signed_by": signer,
        "document": document,
        "problems": [] if signed else export.problems(document),
    }


@router.post("/orders/{order_id}/invoice/sign", response_model=InvoiceOut)
async def sign_invoice(order_id: UUID, ctx: Signer) -> dict[str, Any]:
    async with _session(ctx) as conn, conn.transaction():
        await _order_row(conn, order_id)
        document = await export.sign(
            conn,
            ctx.tenant_id,
            order_id,
            actor_id=ctx.user.id,
            today=await _today(conn, ctx.tenant_id),
        )
        signer = await conn.fetchval("select full_name from profiles where id = $1", ctx.user.id)
        signed_at = await conn.fetchval(
            "select invoice_signed_at from sale_orders where id = $1", order_id
        )
    log.info("invoice_signed", order_id=str(order_id), number=document["number"])
    return {
        "signed": True,
        "signed_at": signed_at,
        "signed_by": signer,
        "document": document,
        "problems": [],
    }


# --------------------------------------------------------------------------
# the bill of lading draft
# --------------------------------------------------------------------------


@router.post("/orders/{order_id}/export/bl-check", response_model=DraftCheckOut)
async def check_bl_draft(
    order_id: UUID, ctx: Seller, file: Annotated[UploadFile, File()]
) -> dict[str, Any]:
    """Read the shipping line's bill of lading draft and compare it with the
    order, before the buyer is asked to confirm it. Keeps the draft on its step;
    confirming is still a person's."""
    data, mime, path = await _upload(ctx, file)
    async with _session(ctx) as conn:
        order = await _order_row(conn, order_id)
        vin = await conn.fetchval("select vin from vehicles where id = $1", order["vehicle_id"])
        today = await _today(conn, ctx.tenant_id)
    proposal = await inbound.read(
        tenant_id=ctx.tenant_id, data=data, mime_type=mime, car_vin=vin, today=today
    )
    checks = export.check_draft(
        proposal,
        vin=vin,
        consignee=order["consignee_name"],
        port=order["port_of_discharge"],
    )
    await storage.upload(path, data, content_type=mime)
    async with _session(ctx) as conn, conn.transaction():
        await export.attach(conn, order_id, "bl_draft_confirmed", path)
    return {
        "checks": [
            {"name": c.name, "ok": c.ok, "expected": c.expected, "found": c.found} for c in checks
        ],
        "clean": all(c.ok is not False for c in checks) and any(c.ok for c in checks),
        "warnings": [w for w in proposal.warnings if "VIN" not in w],
    }


# --------------------------------------------------------------------------
# settings
# --------------------------------------------------------------------------

settings_router = APIRouter(prefix="/v1/settings/documents", tags=["export"])
Settings = Annotated[TenantContext, Depends(require_permission("settings.documents"))]


@settings_router.get("", response_model=export.DocumentSettings)
async def get_document_settings(ctx: Settings) -> export.DocumentSettings:
    async with _session(ctx) as conn:
        return await export.settings_for(conn, ctx.tenant_id)


@settings_router.put("", response_model=export.DocumentSettings)
async def put_document_settings(
    body: export.DocumentSettings, ctx: Settings
) -> export.DocumentSettings:
    """What every document from now on says about the seller. A signed invoice
    keeps what it said."""
    async with _session(ctx) as conn:
        await conn.execute(
            "update tenants set document_settings = $2 where id = $1",
            ctx.tenant_id,
            body.model_dump(),
        )
    return body
