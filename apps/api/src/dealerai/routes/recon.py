"""Reconditioning: the work a car needs before it is sold, inside a budget.

Everything here is the buy side — an estimate is what the dealer will pay — so
every session is cleared only for `costs.view`, and the rows are behind the same
wall in Postgres as the cost ledger (0018_lifecycle_recon.sql).

Who does what:

* `recon.edit` (owner, admin, manager) runs the work: inspects, adds items,
  commits them, records what they cost. A manager runs the workshop.
* `costs.edit` (owner, admin) sets the budget. Whoever commits work cannot be
  whoever moves the line it is measured against.
* An over-budget item is decided in the approvals queue by an owner or admin.

Reading inspection photos is a proposal, like reading an invoice:
`/recon/inspect` returns work and writes nothing; `POST /recon/items` writes
what the person posted back.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

import asyncpg
import structlog
from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from pydantic import BaseModel, Field

from ..core.errors import Forbidden, NotFound, Unusable
from ..deps import TenantContext, require_permission
from ..lifecycle import invoices, recon
from ..media import storage
from .acquisition import MoneyOut, _money, _session, _tenant_currency, _vehicle

log = structlog.get_logger()

router = APIRouter(prefix="/v1/vehicles", tags=["recon"])

Viewer = Annotated[TenantContext, Depends(require_permission("costs.view"))]
Runner = Annotated[TenantContext, Depends(require_permission("recon.edit"))]

ItemStatus = Literal["proposed", "awaiting_approval", "approved", "done", "declined"]


class ItemIn(BaseModel):
    area: recon.Area
    operation: recon.Operation
    quantity: int = Field(default=1, ge=1, le=50)
    description: str = Field(min_length=1, max_length=300)
    severity: recon.Severity | None = None
    vendor: str | None = Field(default=None, max_length=200)
    #: In the dealer's currency. Optional until the work is committed.
    estimate_minor: int | None = Field(default=None, ge=0)
    source: Literal["manual", "photo"] = "manual"
    photo_path: str | None = Field(default=None, max_length=500)


class ItemBatch(BaseModel):
    items: list[ItemIn] = Field(min_length=1, max_length=30)


class ItemPatch(BaseModel):
    area: recon.Area | None = None
    operation: recon.Operation | None = None
    quantity: int | None = Field(default=None, ge=1, le=50)
    description: str | None = Field(default=None, min_length=1, max_length=300)
    severity: recon.Severity | None = None
    vendor: str | None = Field(default=None, max_length=200)
    estimate_minor: int | None = Field(default=None, ge=0)


class DoneIn(BaseModel):
    actual_minor: int = Field(ge=0)
    vendor: str | None = Field(default=None, max_length=200)


class ReconPatch(BaseModel):
    budget_minor: int | None = Field(default=None, ge=0)
    ready_by: date | None = None
    notes: str | None = Field(default=None, max_length=2000)


class ItemOut(BaseModel):
    id: UUID
    area: str
    operation: str
    quantity: int
    description: str
    severity: str | None
    vendor: str | None
    estimate: MoneyOut | None
    actual: MoneyOut | None
    status: ItemStatus
    source: str
    photo_path: str | None
    approval_id: UUID | None
    done_at: datetime | None
    created_at: datetime


class ReconOut(BaseModel):
    vehicle_id: UUID
    currency: str
    #: Null: nobody set one, and every item asks for approval.
    budget: MoneyOut | None
    committed: MoneyOut
    spent: MoneyOut
    remaining: MoneyOut | None
    over_budget: bool
    ready_by: date | None
    ready_at: datetime | None
    #: The expected date has passed and the car is not ready.
    overdue: bool
    #: Days since the record was started, to ready or to today.
    days: int | None
    notes: str | None
    items: list[ItemOut]


class CommitOut(BaseModel):
    item: ItemOut
    #: Set when the item went to the approvals queue instead of being approved.
    approval_id: UUID | None
    over: MoneyOut | None


class FindingOut(BaseModel):
    photo: int
    photo_path: str | None
    area: str
    operation: str
    quantity: int
    severity: str
    description: str
    seen: str
    estimate: MoneyOut | None
    #: "rate_card", "history", or null when a person has to type it.
    estimate_source: str | None


class InspectionOut(BaseModel):
    findings: list[FindingOut]
    warnings: list[str]


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _present_item(row: Any, currency: str) -> dict[str, Any]:
    return {
        "id": row["id"],
        "area": row["area"],
        "operation": row["operation"],
        "quantity": row["quantity"],
        "description": row["description"],
        "severity": row["severity"],
        "vendor": row["vendor"],
        "estimate": _money(row["estimate_minor"], currency),
        "actual": _money(row["actual_minor"], currency),
        "status": row["status"],
        "source": row["source"],
        "photo_path": row["photo_path"],
        "approval_id": row["approval_id"],
        "done_at": row["done_at"],
        "created_at": row["created_at"],
    }


def _photo_path_ok(ctx: TenantContext, path: str | None) -> None:
    """Input from the browser, like an invoice's path: this tenant's, an inspection."""
    if path is not None and not path.startswith(f"{ctx.tenant_id}/inspections/"):
        raise Unusable(
            "that photo is not one of this dealership's inspections",
            ar="هذه الصورة ليست من صور فحص هذا المعرض.",
        )


async def _owned(conn: asyncpg.Connection, vehicle_id: UUID, item_id: UUID) -> None:
    if not await conn.fetchval(
        "select 1 from recon_items where id = $1 and vehicle_id = $2", item_id, vehicle_id
    ):
        raise NotFound("no such item", ar="لا يوجد بند بهذا الرقم.")


async def _record(conn: asyncpg.Connection, ctx: TenantContext, vehicle_id: UUID) -> dict[str, Any]:
    currency = await _tenant_currency(conn, ctx.tenant_id)
    row = await conn.fetchrow(
        "select budget_minor, ready_by, ready_at, notes, created_at from vehicle_recon "
        "where vehicle_id = $1",
        vehicle_id,
    )
    budget = await recon.budget_of(conn, vehicle_id)
    if row is None:
        # Nothing written yet: show the budget it will start with.
        settings = await recon.settings_for(conn, ctx.tenant_id)
        budget = recon.Budget(settings.default_budget_minor, 0, 0)
    items = await conn.fetch(
        "select * from recon_items where vehicle_id = $1 order by created_at", vehicle_id
    )
    ready_at = row["ready_at"] if row else None
    ready_by = row["ready_by"] if row else None
    today = datetime.now(UTC).date()
    days = None
    if row is not None:
        days = ((ready_at or datetime.now(UTC)) - row["created_at"]).days
    return {
        "vehicle_id": vehicle_id,
        "currency": currency,
        "budget": _money(budget.budget_minor, currency),
        "committed": _money(budget.committed_minor, currency),
        "spent": _money(budget.spent_minor, currency),
        "remaining": _money(budget.remaining_minor, currency),
        "over_budget": budget.over,
        "ready_by": ready_by,
        "ready_at": ready_at,
        "overdue": ready_at is None and ready_by is not None and ready_by < today,
        "days": days,
        "notes": row["notes"] if row else None,
        "items": [_present_item(item, currency) for item in items],
    }


# --------------------------------------------------------------------------
# the record
# --------------------------------------------------------------------------


@router.get("/{vehicle_id}/recon", response_model=ReconOut)
async def get_recon(vehicle_id: UUID, ctx: Viewer) -> dict[str, Any]:
    async with _session(ctx) as conn:
        await _vehicle(conn, vehicle_id)
        return await _record(conn, ctx, vehicle_id)


@router.patch("/{vehicle_id}/recon", response_model=ReconOut)
async def patch_recon(vehicle_id: UUID, body: ReconPatch, ctx: Runner) -> dict[str, Any]:
    changes = body.model_dump(exclude_unset=True)
    if "budget_minor" in changes and not ctx.may("costs.edit"):
        raise Forbidden(
            "setting a reconditioning budget needs an owner or admin",
            ar="تحديد ميزانية التجهيز للمالك أو المدير العام فقط.",
        )
    async with _session(ctx) as conn, conn.transaction():
        await _vehicle(conn, vehicle_id)
        await recon.ensure_record(conn, ctx.tenant_id, vehicle_id)
        for column in ("budget_minor", "ready_by", "notes"):
            if column in changes:
                await conn.execute(
                    f"update vehicle_recon set {column} = $2 where vehicle_id = $1",  # noqa: S608
                    vehicle_id,
                    changes[column],
                )
        if "budget_minor" in changes:
            await conn.execute(
                """insert into audit_log (tenant_id, actor_type, actor_id, action,
                                          entity_type, entity_id, after)
                   values ($1, 'user', $2, 'recon.budget_set', 'vehicle', $3, $4)""",
                ctx.tenant_id,
                str(ctx.user.id),
                vehicle_id,
                {"budget_minor": changes["budget_minor"]},
            )
        return await _record(conn, ctx, vehicle_id)


@router.post("/{vehicle_id}/recon/ready", response_model=ReconOut)
async def mark_ready(vehicle_id: UUID, ctx: Runner) -> dict[str, Any]:
    """The work is finished. A car still in draft goes on sale."""
    async with _session(ctx) as conn, conn.transaction():
        await _vehicle(conn, vehicle_id)
        await recon.mark_ready(conn, ctx.tenant_id, vehicle_id)
        return await _record(conn, ctx, vehicle_id)


# --------------------------------------------------------------------------
# items
# --------------------------------------------------------------------------


@router.post(
    "/{vehicle_id}/recon/items", response_model=list[ItemOut], status_code=status.HTTP_201_CREATED
)
async def add_items(vehicle_id: UUID, body: ItemBatch, ctx: Runner) -> list[dict[str, Any]]:
    """Record proposed work — typed, or confirmed from an inspection. Proposed
    commits no money; all or nothing, like a batch of costs."""
    for item in body.items:
        _photo_path_ok(ctx, item.photo_path)
    out: list[dict[str, Any]] = []
    async with _session(ctx) as conn, conn.transaction():
        await _vehicle(conn, vehicle_id)
        await recon.ensure_record(conn, ctx.tenant_id, vehicle_id)
        currency = await _tenant_currency(conn, ctx.tenant_id)
        for item in body.items:
            row = await conn.fetchrow(
                """insert into recon_items
                     (tenant_id, vehicle_id, area, operation, quantity, description, severity,
                      vendor, estimate_minor, source, photo_path, created_by)
                   values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                   returning *""",
                ctx.tenant_id,
                vehicle_id,
                item.area,
                item.operation,
                item.quantity,
                item.description.strip(),
                item.severity,
                item.vendor,
                item.estimate_minor,
                item.source,
                item.photo_path,
                ctx.user.id,
            )
            out.append(_present_item(row, currency))
    return out


@router.patch("/{vehicle_id}/recon/items/{item_id}", response_model=ItemOut)
async def update_item(
    vehicle_id: UUID, item_id: UUID, body: ItemPatch, ctx: Runner
) -> dict[str, Any]:
    """Correct proposed work. Once committed, an estimate is what was agreed:
    changing it is declining the item and proposing it again."""
    changes = body.model_dump(exclude_unset=True)
    async with _session(ctx) as conn, conn.transaction():
        await _owned(conn, vehicle_id, item_id)
        current = await conn.fetchrow(
            "select status from recon_items where id = $1 for update", item_id
        )
        if current["status"] != "proposed":
            raise Unusable(
                "only proposed work can be changed; decline it and propose it again",
                ar="لا يُعدَّل إلا البند المقترح؛ ارفضه واقترحه من جديد.",
            )
        row = await conn.fetchrow("select * from recon_items where id = $1", item_id)
        merged = {**dict(row), **changes}
        row = await conn.fetchrow(
            """update recon_items
                  set area = $2, operation = $3, quantity = $4, description = $5,
                      severity = $6, vendor = $7, estimate_minor = $8
                where id = $1 returning *""",
            item_id,
            merged["area"],
            merged["operation"],
            merged["quantity"],
            merged["description"],
            merged["severity"],
            merged["vendor"],
            merged["estimate_minor"],
        )
        currency = await _tenant_currency(conn, ctx.tenant_id)
    return _present_item(row, currency)


@router.post("/{vehicle_id}/recon/items/{item_id}/commit", response_model=CommitOut)
async def commit_item(vehicle_id: UUID, item_id: UUID, ctx: Runner) -> dict[str, Any]:
    """Promise the money: approved inside the budget, sent for approval over it."""
    async with _session(ctx) as conn, conn.transaction():
        await _owned(conn, vehicle_id, item_id)
        committed = await recon.commit(conn, ctx.tenant_id, item_id, actor_id=ctx.user.id)
        if committed is None:
            raise NotFound("no such item", ar="لا يوجد بند بهذا الرقم.")
        currency = await _tenant_currency(conn, ctx.tenant_id)
    return {
        "item": _present_item(committed.item, currency),
        "approval_id": committed.approval_id,
        "over": _money(committed.over_minor, currency),
    }


@router.post("/{vehicle_id}/recon/items/{item_id}/done", response_model=ItemOut)
async def complete_item(
    vehicle_id: UUID, item_id: UUID, body: DoneIn, ctx: Runner
) -> dict[str, Any]:
    """The work is done; this is what it cost. The ledger's estimate becomes it."""
    async with _session(ctx) as conn, conn.transaction():
        await _owned(conn, vehicle_id, item_id)
        done = await recon.finish(
            conn,
            ctx.tenant_id,
            item_id,
            actual_minor=body.actual_minor,
            vendor=body.vendor,
            actor_id=ctx.user.id,
        )
        if done is None:
            raise NotFound("no such item", ar="لا يوجد بند بهذا الرقم.")
        currency = await _tenant_currency(conn, ctx.tenant_id)
    return _present_item(done.item, currency)


@router.post("/{vehicle_id}/recon/items/{item_id}/decline", response_model=ItemOut)
async def decline_item(vehicle_id: UUID, item_id: UUID, ctx: Runner) -> dict[str, Any]:
    async with _session(ctx) as conn, conn.transaction():
        await _owned(conn, vehicle_id, item_id)
        row = await recon.decline(conn, ctx.tenant_id, item_id, actor_id=ctx.user.id)
        if row is None:
            raise NotFound("no such item", ar="لا يوجد بند بهذا الرقم.")
        currency = await _tenant_currency(conn, ctx.tenant_id)
    return _present_item(row, currency)


# --------------------------------------------------------------------------
# reading inspection photos
# --------------------------------------------------------------------------

_PHOTO_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})


@router.post("/{vehicle_id}/recon/inspect", response_model=InspectionOut)
async def inspect(
    vehicle_id: UUID,
    ctx: Runner,
    files: Annotated[list[UploadFile], File()],
    note: Annotated[str | None, Form(max_length=300)] = None,
) -> dict[str, Any]:
    """Read inspection photos into proposed work, priced from the dealer's own
    rates or history. Writes no item."""
    if not 1 <= len(files) <= recon.MAX_PHOTOS:
        raise Unusable(
            f"send between 1 and {recon.MAX_PHOTOS} photos",
            ar=f"أرسل من صورة واحدة إلى {recon.MAX_PHOTOS} صور.",
        )
    photos: list[tuple[bytes, str]] = []
    for upload in files:
        mime = (upload.content_type or "").split(";")[0].strip().lower()
        if mime not in _PHOTO_TYPES:
            raise Unusable(
                "an inspection photo is a JPEG, PNG or WebP",
                ar="صورة الفحص تكون بصيغة JPEG أو PNG أو WebP.",
            )
        data = await upload.read()
        if not data or len(data) > invoices.MAX_BYTES:
            raise Unusable(
                "each photo must be under 15 MB and not empty",
                ar="كل صورة يجب ألا تكون فارغة وأن تكون أصغر من ١٥ ميجابايت.",
            )
        photos.append((data, mime))

    async with _session(ctx) as conn:
        car = await conn.fetchrow(
            "select make, model, model_year, mileage_km from vehicles where id = $1", vehicle_id
        )
        if car is None:
            raise NotFound("no such vehicle", ar="لا توجد سيارة بهذا الرقم.")
    described = " ".join(str(p) for p in (car["model_year"], car["make"], car["model"]) if p)
    hint = f"The car is a {described}" + (
        f" with {car['mileage_km']:,} km." if car["mileage_km"] else "."
    )
    if note:
        hint += f" The dealer adds: {note}"

    reading = await recon.inspect(tenant_id=ctx.tenant_id, photos=photos, hint=hint)

    # Kept after the reading, as an invoice is, so the approver can see why.
    paths: list[str | None] = []
    for data, mime in photos:
        try:
            path = storage.object_path(ctx.tenant_id, "inspections", storage.extension_for(mime))
            await storage.upload(path, data, content_type=mime)
            paths.append(path)
        except Exception as exc:  # noqa: BLE001 - the reading is still worth showing
            log.warning("inspection_photo_not_stored", error=str(exc))
            paths.append(None)

    findings: list[dict[str, Any]] = []
    async with _session(ctx) as conn:
        settings = await recon.settings_for(conn, ctx.tenant_id)
        currency = await _tenant_currency(conn, ctx.tenant_id)
        for finding in reading.findings:
            amount, source = await recon.estimate(
                conn, ctx.tenant_id, settings, finding.operation, finding.quantity
            )
            findings.append(
                {
                    **finding.model_dump(),
                    "photo_path": paths[finding.photo - 1],
                    "estimate": _money(amount, currency),
                    "estimate_source": source,
                }
            )
    if None in paths:
        reading.warnings.append("a photo could not be kept; the findings are still usable")
    return {"findings": findings, "warnings": reading.warnings}


# --------------------------------------------------------------------------
# settings
# --------------------------------------------------------------------------

settings_router = APIRouter(prefix="/v1/settings/recon", tags=["recon"])
Settings = Annotated[TenantContext, Depends(require_permission("settings.recon"))]


@settings_router.get("", response_model=recon.ReconSettings)
async def get_recon_settings(ctx: Settings) -> recon.ReconSettings:
    async with _session(ctx) as conn:
        return await recon.settings_for(conn, ctx.tenant_id)


@settings_router.put("", response_model=recon.ReconSettings)
async def put_recon_settings(body: recon.ReconSettings, ctx: Settings) -> recon.ReconSettings:
    """Changing these changes the budget new records start with and tomorrow's
    estimates. A car's own budget stays what it was set to."""
    async with _session(ctx) as conn:
        await conn.execute(
            "update tenants set recon_settings = $2 where id = $1",
            ctx.tenant_id,
            body.model_dump(),
        )
    return body
