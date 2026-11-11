"""The export file: Pollux's own procedure for each destination, the papers each
step produces, and the commercial invoice, drafted from the record and signed by
a person.

The procedures are Pollux's, from its own website (docs/lifecycle/pollux.md):
eleven steps to Algeria, eleven to Tunisia — with Dubai export plates and no
Chamber certificate — nine everywhere else, with the customs card. A local sale
is registered at RTA and handed over. The slice's exit criterion: **every
document for one sale is drafted from the record and a person signs it, and an
export car shows which step of its destination's procedure it is on.**

Where the AI is: checking the bill of lading draft before the original is
issued. Step 7 of Pollux's procedure is "confirm the bill of lading draft with
the customer" — the moment a wrong consignee or a mistyped VIN is still free to
fix. The draft is read by L4's shipping reader and compared, in code, with the
order: the VIN, the consignee, the port. The model reads; it does not decide
what matches.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal
from uuid import UUID

import asyncpg
from pydantic import BaseModel, Field

from ..core.errors import Conflict
from .deals import load_order
from .inbound import ShippingProposal, normal_vin

Procedure = Literal["DZ", "TN", "other", "local"]

PROCEDURES: dict[str, tuple[str, ...]] = {
    "DZ": (
        "customer_documents",
        "assign_vehicle",
        "book_shipping",
        "export_inspection",
        "deliver_to_carrier",
        "export_certificate",
        "bl_draft_confirmed",
        "bl_original",
        "chamber_certificate",
        "commercial_invoice",
        "file_delivered",
    ),
    "TN": (
        "customer_documents",
        "assign_vehicle",
        "book_shipping",
        "export_inspection",
        "export_plates",
        "deliver_to_carrier",
        "export_certificate",
        "bl_draft_confirmed",
        "bl_original",
        "commercial_invoice",
        "file_delivered",
    ),
    "other": (
        "customer_documents",
        "assign_vehicle",
        "customs_card",
        "book_shipping",
        "export_certificate",
        "bl_draft_confirmed",
        "bl_original",
        "commercial_invoice",
        "file_delivered",
    ),
    "local": (
        "customer_documents",
        "assign_vehicle",
        "rta_registration",
        "commercial_invoice",
        "delivered",
    ),
}

#: Steps that produce a paper somebody uploads. The commercial invoice is drafted
#: here instead, and the bill of lading draft is checked rather than just kept.
PAPERS = frozenset(
    {
        "customer_documents",
        "customs_card",
        "export_inspection",
        "export_plates",
        "export_certificate",
        "bl_draft_confirmed",
        "bl_original",
        "chamber_certificate",
        "rta_registration",
    }
)


def procedure_for(purchase_type: str, destination: str | None) -> Procedure:
    if purchase_type == "local":
        return "local"
    if destination in ("DZ", "TN"):
        return destination  # type: ignore[return-value]
    return "other"


def stage(steps: list[dict[str, Any]]) -> str | None:
    """The step after the furthest one reached — as for a car coming in."""
    furthest = max((i for i, s in enumerate(steps) if s["status"] != "pending"), default=-1)
    return next((s["code"] for s in steps[furthest + 1 :] if s["status"] == "pending"), None)


# --------------------------------------------------------------------------
# the steps
# --------------------------------------------------------------------------


async def start(conn: asyncpg.Connection, tenant_id: UUID, order_id: UUID) -> None:
    """Lay out the order's procedure, once. The destination decides which."""
    if await conn.fetchval("select 1 from order_steps where order_id = $1 limit 1", order_id):
        return
    order = await conn.fetchrow(
        "select purchase_type, destination from sale_orders where id = $1", order_id
    )
    for position, code in enumerate(
        PROCEDURES[procedure_for(order["purchase_type"], order["destination"])]
    ):
        await conn.execute(
            """insert into order_steps (order_id, tenant_id, code, position)
               values ($1, $2, $3, $4)""",
            order_id,
            tenant_id,
            code,
            position,
        )


async def mark(
    conn: asyncpg.Connection,
    order_id: UUID,
    code: str,
    *,
    status: Literal["pending", "done", "skipped"],
    done_on: date | None = None,
    note: str | None = None,
) -> bool:
    """Move one step. The invoice is done by signing it; the file is delivered
    only when everything before it is done or skipped."""
    if code == "commercial_invoice" and status == "done":
        raise Conflict(
            "the commercial invoice is done by signing it",
            ar="تكتمل الفاتورة التجارية بتوقيعها.",
        )
    if code in ("file_delivered", "delivered") and status == "done":
        open_steps = await conn.fetchval(
            """select count(*) from order_steps
                where order_id = $1 and code <> $2 and status = 'pending'""",
            order_id,
            code,
        )
        if open_steps:
            raise Conflict(
                f"{open_steps} step(s) before this one are not done",
                ar=f"ما زالت {open_steps} من الخطوات السابقة غير مكتملة.",
            )
    updated = await conn.fetchval(
        """update order_steps
              set status = $3,
                  done_on = case when $3 = 'done' then coalesce($4, current_date) end,
                  note = coalesce($5, note)
            where order_id = $1 and code = $2
        returning code""",
        order_id,
        code,
        status,
        done_on,
        note,
    )
    return updated is not None


async def attach(conn: asyncpg.Connection, order_id: UUID, code: str, path: str) -> bool:
    """Keep the paper a step produced. Kept is done — except the bill of lading
    draft, which is done when the customer confirms it, not when it arrives."""
    done = code != "bl_draft_confirmed"
    updated = await conn.fetchval(
        """update order_steps
              set document_path = $3,
                  status = case when $4 then 'done' else status end,
                  done_on = case when $4 then coalesce(done_on, current_date) else done_on end
            where order_id = $1 and code = $2
        returning code""",
        order_id,
        code,
        path,
        done,
    )
    return updated is not None


# --------------------------------------------------------------------------
# the commercial invoice
# --------------------------------------------------------------------------


class DocumentSettings(BaseModel):
    """Who the documents say sold the car."""

    legal_name: str | None = Field(default=None, max_length=200)
    address: str | None = Field(default=None, max_length=500)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=200)
    #: Tax registration number, printed when there is one.
    trn: str | None = Field(default=None, max_length=40)
    invoice_prefix: str = Field(default="INV", min_length=1, max_length=12)


async def settings_for(conn: asyncpg.Connection, tenant_id: UUID) -> DocumentSettings:
    raw = await conn.fetchval("select document_settings from tenants where id = $1", tenant_id)
    return DocumentSettings.model_validate(raw or {})


_CAR = """select model_year, make, model, trim, vin, exterior_color, engine, fuel, transmission,
                 mileage_km, stock_number, vehicle_condition
            from vehicles where id = $1"""


def draft_invoice(
    *,
    seller: DocumentSettings,
    tenant_name: str,
    order: asyncpg.Record | dict[str, Any],
    car: asyncpg.Record | dict[str, Any],
    lines: list[dict[str, Any]],
    issued_on: date,
    number: str | None,
) -> dict[str, Any]:
    """The commercial invoice, from the record and nothing else. Pure: every
    figure on it is a figure in the order, and its total is their sum."""
    description = " ".join(
        str(p) for p in (car["model_year"], car["make"], car["model"], car["trim"]) if p
    )
    return {
        "number": number,
        "issued_on": issued_on.isoformat(),
        "currency": order["currency"],
        "seller": {
            "name": seller.legal_name or tenant_name,
            "address": seller.address,
            "phone": seller.phone,
            "email": seller.email,
            "trn": seller.trn,
        },
        "buyer": {"name": order["buyer_name"]},
        "consignee": {
            "name": order["consignee_name"],
            "address": order["consignee_address"],
            "phone": order["consignee_phone"],
        },
        "sale": {
            "type": order["purchase_type"],
            "destination": order["destination"],
            "port_of_discharge": order["port_of_discharge"],
            "shipping_method": order["shipping_method"],
        },
        "vehicle": {
            "description": description,
            "vin": car["vin"],
            "condition": car["vehicle_condition"],
            "colour": car["exterior_color"],
            "engine": car["engine"],
            "fuel": car["fuel"],
            "transmission": car["transmission"],
            "mileage_km": car["mileage_km"],
            "stock_number": car["stock_number"],
        },
        "lines": [
            {
                "kind": line["kind"],
                "description": line["description"]
                or (description if line["kind"] == "vehicle" else None),
                "amount_minor": int(line["amount_minor"]),
            }
            for line in lines
        ],
        "total_minor": sum(int(line["amount_minor"]) for line in lines),
    }


def problems(invoice: dict[str, Any]) -> list[str]:
    """What stops this invoice being signed. Customs reads a commercial invoice
    for the chassis number and the consignee; one without them is a paper that
    stops the car at the port."""
    found: list[str] = []
    if not invoice["vehicle"]["vin"]:
        found.append("the car has no VIN")
    if invoice["sale"]["type"] == "export" and not invoice["consignee"]["name"]:
        found.append("the consignee is not recorded")
    if invoice["sale"]["type"] == "export" and not invoice["consignee"]["address"]:
        found.append("the consignee's address is not recorded")
    if not invoice["seller"]["address"]:
        found.append("the seller's address is not set in Settings → Documents")
    return found


async def current_invoice(
    conn: asyncpg.Connection, tenant_id: UUID, order_id: UUID, *, today: date
) -> dict[str, Any] | None:
    """The signed invoice as it was signed, or a draft from the record as it is."""
    order = await conn.fetchrow("select * from sale_orders where id = $1", order_id)
    if order is None:
        return None
    if order["invoice"] is not None:
        return dict(order["invoice"])
    car = await conn.fetchrow(_CAR, order["vehicle_id"])
    lines = [
        dict(r)
        for r in await conn.fetch(
            """select kind, description, amount_minor from sale_charges
                where order_id = $1 order by position""",
            order_id,
        )
    ]
    tenant_name = await conn.fetchval("select name from tenants where id = $1", tenant_id)
    return draft_invoice(
        seller=await settings_for(conn, tenant_id),
        tenant_name=tenant_name,
        order=order,
        car=car,
        lines=lines,
        issued_on=today,
        number=None,
    )


async def sign(
    conn: asyncpg.Connection, tenant_id: UUID, order_id: UUID, *, actor_id: UUID, today: date
) -> dict[str, Any]:
    """A person signs the invoice: it gets its number, what it says is kept as it
    says it, and the step is done. Signing twice is refused."""
    order = await load_order(conn, order_id, lock=True)
    if order is None:
        raise Conflict("no such order", ar="لا يوجد طلب بهذا الرقم.")
    if order.row["invoice_number"] is not None:
        raise Conflict("this invoice is already signed", ar="هذه الفاتورة موقّعة بالفعل.")
    if order.row["status"] not in ("reserved", "completed"):
        raise Conflict(
            "an invoice is signed for a car somebody has reserved",
            ar="تُوقَّع الفاتورة لسيارة محجوزة لمشترٍ.",
        )
    draft = await current_invoice(conn, tenant_id, order_id, today=today)
    assert draft is not None  # noqa: S101 - the order was just loaded
    blocking = problems(draft)
    if blocking:
        raise Conflict(
            "the invoice cannot be signed: " + "; ".join(blocking),
            ar="لا يمكن توقيع الفاتورة قبل استكمال بياناتها.",
        )
    settings = await settings_for(conn, tenant_id)
    # The tenant row is the lock: two invoices signed at once cannot take one number.
    await conn.execute("select 1 from tenants where id = $1 for update", tenant_id)
    year = today.year
    prefix = f"{settings.invoice_prefix}-{year}-"
    last = await conn.fetchval(
        """select max(substring(invoice_number from length($2) + 1)::int) from sale_orders
            where tenant_id = $1 and invoice_number like $2 || '%'""",
        tenant_id,
        prefix,
    )
    number = f"{prefix}{(last or 0) + 1:04d}"
    signed = {**draft, "number": number, "issued_on": today.isoformat()}
    await conn.execute(
        """update sale_orders
              set invoice_number = $2, invoice = $3, invoice_signed_by = $4,
                  invoice_signed_at = now()
            where id = $1""",
        order_id,
        number,
        signed,
        actor_id,
    )
    await conn.execute(
        """update order_steps set status = 'done', done_on = $2
            where order_id = $1 and code = 'commercial_invoice'""",
        order_id,
        today,
    )
    return signed


# --------------------------------------------------------------------------
# checking the bill of lading draft
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Check:
    #: "vin", "consignee", "port".
    name: str
    #: True matches, False does not, None could not be compared.
    ok: bool | None
    expected: str | None
    found: str | None


def _plain(text: str | None) -> str:
    return re.sub(r"[^0-9a-z؀-ۿ]+", " ", (text or "").casefold()).strip()


def _same(expected: str | None, found: str | None) -> bool | None:
    if not expected or not found:
        return None
    a, b = _plain(expected), _plain(found)
    return a in b or b in a


def check_draft(
    proposal: ShippingProposal,
    *,
    vin: str | None,
    consignee: str | None,
    port: str | None,
) -> list[Check]:
    """Compare a bill of lading draft with the order. Pure.

    The VIN must be on it — not "near enough": a draft for another chassis is
    another car's draft. The consignee and the port are compared as names
    (case, spacing and punctuation aside), because "SARL ATLAS AUTO" and
    "Sarl Atlas Auto." are the same company and a person can see that.
    """
    return [
        Check(
            name="vin",
            ok=proposal.matches if vin else None,
            expected=normal_vin(vin) if vin else None,
            found=", ".join(proposal.vins) or None,
        ),
        Check(
            name="consignee",
            ok=_same(consignee, proposal.consignee),
            expected=consignee,
            found=proposal.consignee,
        ),
        Check(
            name="port",
            ok=_same(port, proposal.port_of_discharge),
            expected=port,
            found=proposal.port_of_discharge,
        ),
    ]
