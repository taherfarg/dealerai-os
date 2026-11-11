"""Getting a car ready to sell, inside a budget.

A car is bought with work to do: paint, dents, tyres, a service, a valet. Each
piece of work is an item on the car's reconditioning record, and the rule this
module exists for is the slice's exit criterion — **a repair that would take
the car over its budget raises an approval before the money is spent.**

* **Committing** an item is the moment money is promised. Within the budget it
  is approved at once and its estimate joins the ledger as an estimate line, so
  the landed cost (and tomorrow's price) counts it before the bill arrives.
  Over the budget it waits in the approvals queue for an owner or admin. No
  budget set spends like a budget of nothing.
* **Done** turns the estimate line into the actual amount. A repair that came
  in above its estimate is money already spent: nothing can be stopped, so the
  owner is told instead.

Where the AI is: reading inspection photos into proposed work. The model says
what it sees and what work that calls for. It never says what the work costs —
that comes from the dealer's rate card, or from what the same operation cost
this dealer the last few times, or from a person. A repair price from a model's
memory is a guess about a workshop it has never been to.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated, Literal
from uuid import UUID

import asyncpg
import structlog
from google.genai import types
from pydantic import BaseModel, Field

from ..ai.gateway import SystemLayers, complete
from ..ai.models import TaskKind
from ..ai.prompts import load
from ..core.errors import Conflict
from ..core.money import Money
from ..events.bus import emit
from ..orchestrator.approvals import request_approval

log = structlog.get_logger()

Area = Literal["exterior", "interior", "mechanical", "tyres_wheels", "glass", "electrical", "other"]
Operation = Literal[
    "paint_panel",
    "dent_repair",
    "scratch_polish",
    "replace_part",
    "tyre",
    "windscreen",
    "wheel_refurb",
    "interior_clean",
    "upholstery",
    "mechanical",
    "service",
    "detailing",
    "other",
]
Severity = Literal["minor", "moderate", "major"]

#: The ledger category an operation's cost is recorded under.
CATEGORY: dict[str, str] = {
    "replace_part": "parts",
    "tyre": "parts",
    "interior_clean": "detailing",
    "detailing": "detailing",
}

KIND = "recon_over_budget"

#: Statuses whose amount counts against the budget.
COMMITTED = ("approved", "done")
#: Statuses that mean the car still has work in hand.
OPEN = ("awaiting_approval", "approved")

#: How many past jobs of one operation make a history worth estimating from,
#: and how far back they may be.
HISTORY_SAMPLES = 3
HISTORY_DAYS = 365

MAX_PHOTOS = 8


class ReconSettings(BaseModel):
    """A dealership's reconditioning rules, in its own currency's minor units."""

    #: What a car's budget starts at. None: no budget until somebody sets one,
    #: so every repair asks.
    default_budget_minor: int | None = Field(default=None, ge=0, le=10**12)
    #: Per unit of an operation: one panel, one tyre, one valet.
    rates: dict[Operation, Annotated[int, Field(ge=0, le=10**10)]] = Field(default_factory=dict)


async def settings_for(conn: asyncpg.Connection, tenant_id: UUID) -> ReconSettings:
    raw = await conn.fetchval("select recon_settings from tenants where id = $1", tenant_id)
    return ReconSettings.model_validate(raw or {})


# --------------------------------------------------------------------------
# the budget — pure
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Budget:
    budget_minor: int | None
    #: Approved estimates plus the actual amount of work done.
    committed_minor: int
    spent_minor: int

    @property
    def remaining_minor(self) -> int | None:
        return None if self.budget_minor is None else self.budget_minor - self.committed_minor

    @property
    def over(self) -> bool:
        return self.budget_minor is not None and self.committed_minor > self.budget_minor


def needs_approval(budget: Budget, estimate_minor: int) -> bool:
    """Would committing this much take the car over? No budget is no headroom."""
    if budget.budget_minor is None:
        return True
    return budget.committed_minor + estimate_minor > budget.budget_minor


# --------------------------------------------------------------------------
# reading the record
# --------------------------------------------------------------------------

_BUDGET = """
select r.budget_minor,
       coalesce(sum(case when i.status = 'approved' then i.estimate_minor
                         when i.status = 'done' then i.actual_minor end), 0)::bigint
         as committed_minor,
       coalesce(sum(i.actual_minor) filter (where i.status = 'done'), 0)::bigint as spent_minor
  from vehicle_recon r
  left join recon_items i on i.vehicle_id = r.vehicle_id
 where r.vehicle_id = $1
 group by r.budget_minor
"""


async def budget_of(conn: asyncpg.Connection, vehicle_id: UUID) -> Budget:
    row = await conn.fetchrow(_BUDGET, vehicle_id)
    if row is None:
        return Budget(budget_minor=None, committed_minor=0, spent_minor=0)
    return Budget(
        budget_minor=row["budget_minor"],
        committed_minor=int(row["committed_minor"]),
        spent_minor=int(row["spent_minor"]),
    )


async def ensure_record(conn: asyncpg.Connection, tenant_id: UUID, vehicle_id: UUID) -> None:
    """The car's record, created with the dealer's default budget the first
    time anybody writes to it. Reading never creates one."""
    settings = await settings_for(conn, tenant_id)
    await conn.execute(
        """insert into vehicle_recon (vehicle_id, tenant_id, budget_minor)
           values ($1, $2, $3) on conflict (vehicle_id) do nothing""",
        vehicle_id,
        tenant_id,
        settings.default_budget_minor,
    )


async def estimate(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    settings: ReconSettings,
    operation: Operation,
    quantity: int,
) -> tuple[int | None, str | None]:
    """What this work should cost, and where that figure came from.

    The rate card first: it is what the dealer said. Then this dealer's own
    history — the median per unit of the last jobs of the same operation, so
    one bad invoice does not move it. Otherwise nothing, and a person types it.
    """
    rate = settings.rates.get(operation)
    if rate:
        return rate * quantity, "rate_card"
    row = await conn.fetchrow(
        """select count(*) as n,
                  percentile_disc(0.5) within group (order by per_unit) as median
             from (select actual_minor / quantity as per_unit
                     from recon_items
                    where tenant_id = $1 and operation = $2 and status = 'done'
                      and done_at > now() - make_interval(days => $3)
                    order by done_at desc
                    limit 20) recent""",
        tenant_id,
        operation,
        HISTORY_DAYS,
    )
    if row is not None and row["n"] >= HISTORY_SAMPLES and row["median"] is not None:
        return int(row["median"]) * quantity, "history"
    return None, None


# --------------------------------------------------------------------------
# moving an item along
# --------------------------------------------------------------------------


def _label(car: asyncpg.Record) -> str:
    return " ".join(str(p) for p in (car["model_year"], car["make"], car["model"]) if p)


async def _audit(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    actor_id: UUID | str | None,
    action: str,
    item: asyncpg.Record,
) -> None:
    """Every change that moves money on the buy side has a name beside it."""
    await conn.execute(
        """insert into audit_log (tenant_id, actor_type, actor_id, action, entity_type,
                                  entity_id, after)
           values ($1, 'user', $2, $3, 'recon_item', $4, $5)""",
        tenant_id,
        str(actor_id) if actor_id else None,
        action,
        item["id"],
        {
            "status": item["status"],
            "estimate_minor": item["estimate_minor"],
            "actual_minor": item["actual_minor"],
            "cost_id": str(item["cost_id"]) if item["cost_id"] else None,
        },
    )


async def _item(conn: asyncpg.Connection, item_id: UUID) -> asyncpg.Record | None:
    return await conn.fetchrow("select * from recon_items where id = $1 for update", item_id)


async def _tenant_currency(conn: asyncpg.Connection, tenant_id: UUID) -> str:
    return str(await conn.fetchval("select currency from tenants where id = $1", tenant_id))


async def _approve(
    conn: asyncpg.Connection, tenant_id: UUID, item: asyncpg.Record, actor_id: UUID | str | None
) -> asyncpg.Record:
    """Approved: the estimate goes into the ledger, as an estimate."""
    currency = await _tenant_currency(conn, tenant_id)
    cost_id = await conn.fetchval(
        """insert into vehicle_costs
             (tenant_id, vehicle_id, category, description, vendor, amount_minor, currency,
              fx_rate, amount_tenant_minor, incurred_at, status, source, created_by)
           values ($1,$2,$3,$4,$5,$6,$7,1,$6,current_date,'estimate','manual',$8)
           returning id""",
        tenant_id,
        item["vehicle_id"],
        CATEGORY.get(item["operation"], "repair"),
        item["description"],
        item["vendor"],
        item["estimate_minor"],
        currency,
        actor_id,
    )
    row = await conn.fetchrow(
        """update recon_items set status = 'approved', cost_id = $2
            where id = $1 returning *""",
        item["id"],
        cost_id,
    )
    await _audit(conn, tenant_id, actor_id, "recon_item.approved", row)
    return row


@dataclass(slots=True)
class Committed:
    item: asyncpg.Record
    approval_id: UUID | None = None
    #: Over budget by this much, when it had to ask.
    over_minor: int | None = None
    budget: Budget | None = field(default=None)


async def commit(
    conn: asyncpg.Connection, tenant_id: UUID, item_id: UUID, *, actor_id: UUID
) -> Committed | None:
    """Promise the money for one item: approved within the budget, asked for
    over it. Returns None when there is no such item."""
    item = await _item(conn, item_id)
    if item is None:
        return None
    if item["status"] != "proposed":
        raise Conflict(
            f"this item is {item['status']}, not proposed",
            ar="لا يمكن اعتماد هذا البند في حالته الحالية.",
        )
    if item["estimate_minor"] is None:
        raise Conflict(
            "an item needs an estimate before the work is committed",
            ar="أدخل تقدير التكلفة قبل اعتماد العمل.",
        )
    # Locked, so two items committed at once cannot each fit a budget they
    # overrun together.
    await ensure_record(conn, tenant_id, item["vehicle_id"])
    await conn.execute(
        "select 1 from vehicle_recon where vehicle_id = $1 for update", item["vehicle_id"]
    )
    budget = await budget_of(conn, item["vehicle_id"])
    estimate_minor = int(item["estimate_minor"])

    if not needs_approval(budget, estimate_minor):
        return Committed(item=await _approve(conn, tenant_id, item, actor_id), budget=budget)

    over = budget.committed_minor + estimate_minor - (budget.budget_minor or 0)
    currency = await _tenant_currency(conn, tenant_id)
    car = await conn.fetchrow(
        "select make, model, model_year from vehicles where id = $1", item["vehicle_id"]
    )
    over_words = (
        f"{Money(over, currency).display()} over budget"
        if budget.budget_minor is not None
        else "no budget set"
    )
    approval_id = await request_approval(
        conn,
        tenant_id=tenant_id,
        kind=KIND,
        summary=(
            f"{_label(car)} · {item['description']} · "
            f"{Money(estimate_minor, currency).display()} · {over_words}"
        ),
        payload={
            "item_id": str(item["id"]),
            "vehicle_id": str(item["vehicle_id"]),
            "estimate_minor": estimate_minor,
            "committed_minor": budget.committed_minor,
            "budget_minor": budget.budget_minor,
            "over_minor": over,
            "currency": currency,
        },
        entity_type="vehicle",
        entity_id=item["vehicle_id"],
    )
    row = await conn.fetchrow(
        """update recon_items set status = 'awaiting_approval', approval_id = $2
            where id = $1 returning *""",
        item["id"],
        approval_id,
    )
    await _audit(conn, tenant_id, actor_id, "recon_item.asked", row)
    return Committed(item=row, approval_id=approval_id, over_minor=over, budget=budget)


async def apply_decision(conn: asyncpg.Connection, tenant_id: UUID, approval_id: UUID) -> str:
    """A decision on an over-budget item, carried out. Returns what happened."""
    approval = await conn.fetchrow(
        "select status, payload, decided_by from approvals where id = $1 and kind = $2",
        approval_id,
        KIND,
    )
    if approval is None or approval["status"] not in ("approved", "rejected"):
        return "not decided"
    payload = approval["payload"] or {}
    item = await _item(conn, UUID(str(payload["item_id"])))
    if (
        item is None
        or item["status"] != "awaiting_approval"
        or item["approval_id"] != approval_id
        or item["estimate_minor"] != payload.get("estimate_minor")
    ):
        # Withdrawn, or changed, since it was asked about. What was approved is
        # not what is there.
        return "stale"
    if approval["status"] == "rejected":
        row = await conn.fetchrow(
            "update recon_items set status = 'declined' where id = $1 returning *", item["id"]
        )
        await _audit(conn, tenant_id, approval["decided_by"], "recon_item.declined", row)
        return "declined"
    await _approve(conn, tenant_id, item, approval["decided_by"])
    return "applied"


@dataclass(frozen=True, slots=True)
class Done:
    item: asyncpg.Record
    budget: Budget
    #: Came in above its estimate and the car is now over budget.
    overran: bool


async def finish(
    conn: asyncpg.Connection,
    tenant_id: UUID,
    item_id: UUID,
    *,
    actual_minor: int,
    vendor: str | None,
    actor_id: UUID,
) -> Done | None:
    """The work is done and this is what it cost: the estimate line becomes the
    actual amount."""
    item = await _item(conn, item_id)
    if item is None:
        return None
    if item["status"] != "approved":
        raise Conflict(
            f"only approved work can be done; this item is {item['status']}",
            ar="لا يُسجَّل إنجاز إلا لعمل معتمد.",
        )
    vendor = vendor or item["vendor"]
    cost_id = item["cost_id"]
    updated = None
    if cost_id is not None:
        updated = await conn.fetchval(
            """update vehicle_costs
                  set amount_minor = $2, amount_tenant_minor = $2, status = 'actual',
                      vendor = $3, incurred_at = current_date
                where id = $1 returning id""",
            cost_id,
            actual_minor,
            vendor,
        )
    if updated is None:
        # Somebody deleted the estimate line from the ledger by hand. The work
        # still cost what it cost.
        currency = await _tenant_currency(conn, tenant_id)
        cost_id = await conn.fetchval(
            """insert into vehicle_costs
                 (tenant_id, vehicle_id, category, description, vendor, amount_minor, currency,
                  fx_rate, amount_tenant_minor, incurred_at, status, source, created_by)
               values ($1,$2,$3,$4,$5,$6,$7,1,$6,current_date,'actual','manual',$8)
               returning id""",
            tenant_id,
            item["vehicle_id"],
            CATEGORY.get(item["operation"], "repair"),
            item["description"],
            vendor,
            actual_minor,
            currency,
            actor_id,
        )
    row = await conn.fetchrow(
        """update recon_items
              set status = 'done', actual_minor = $2, vendor = $3, cost_id = $4,
                  done_at = now()
            where id = $1 returning *""",
        item["id"],
        actual_minor,
        vendor,
        cost_id,
    )
    await _audit(conn, tenant_id, actor_id, "recon_item.done", row)
    budget = await budget_of(conn, item["vehicle_id"])
    overran = actual_minor > int(item["estimate_minor"]) and budget.over
    if overran:
        await emit(
            conn,
            "recon.overran",
            {
                "vehicle_id": str(item["vehicle_id"]),
                "item_id": str(item["id"]),
                "description": item["description"],
                "estimate_minor": int(item["estimate_minor"]),
                "actual_minor": actual_minor,
                "over_minor": budget.committed_minor - (budget.budget_minor or 0),
                "currency": await _tenant_currency(conn, tenant_id),
            },
            tenant_id=tenant_id,
            dedupe_key=f"recon.overran:{item['id']}",
        )
    return Done(item=row, budget=budget, overran=overran)


async def decline(
    conn: asyncpg.Connection, tenant_id: UUID, item_id: UUID, *, actor_id: UUID
) -> asyncpg.Record | None:
    """Not doing this work. An approved item's estimate leaves the ledger; one
    waiting for approval is withdrawn from the queue."""
    item = await _item(conn, item_id)
    if item is None:
        return None
    if item["status"] in ("done", "declined"):
        raise Conflict(
            f"this item is already {item['status']}",
            ar="هذا البند منتهٍ بالفعل.",
        )
    if item["cost_id"] is not None and item["status"] == "approved":
        await conn.execute(
            "delete from vehicle_costs where id = $1 and status = 'estimate'", item["cost_id"]
        )
    if item["status"] == "awaiting_approval" and item["approval_id"] is not None:
        await conn.execute(
            """update approvals
                  set status = 'rejected', decided_at = now(), decision_note = 'withdrawn'
                where id = $1 and status = 'pending'""",
            item["approval_id"],
        )
    row = await conn.fetchrow(
        "update recon_items set status = 'declined', cost_id = null where id = $1 returning *",
        item["id"],
    )
    await _audit(conn, tenant_id, actor_id, "recon_item.declined", row)
    return row


async def mark_ready(conn: asyncpg.Connection, tenant_id: UUID, vehicle_id: UUID) -> None:
    """The work is finished and the car can be sold. A car still in draft goes
    on sale; one already on sale stays as it is."""
    open_items = await conn.fetchval(
        "select count(*) from recon_items where vehicle_id = $1 and status = any($2::text[])",
        vehicle_id,
        list(OPEN),
    )
    if open_items:
        raise Conflict(
            f"{open_items} item(s) are still approved or waiting for approval",
            ar=f"ما زال {open_items} من البنود معتمدًا أو بانتظار الموافقة.",
        )
    await ensure_record(conn, tenant_id, vehicle_id)
    await conn.execute(
        "update vehicle_recon set ready_at = now() where vehicle_id = $1", vehicle_id
    )
    went_on_sale = await conn.fetchval(
        """update vehicles set status = 'available'
            where id = $1 and status = 'draft' returning id""",
        vehicle_id,
    )
    if went_on_sale:
        await emit(
            conn,
            "vehicle.status_changed",
            {"vehicle_id": str(vehicle_id), "status": "available", "reason": "reconditioned"},
            tenant_id=tenant_id,
        )


# --------------------------------------------------------------------------
# reading inspection photos
# --------------------------------------------------------------------------


class Finding(BaseModel):
    """One piece of work the model sees a need for. Loose on purpose: a number
    out of range is corrected here rather than failing the whole reading."""

    photo: int = Field(description="Which photo shows it, counting from 1.")
    area: Area
    operation: Operation
    quantity: int = Field(description="Panels, tyres, wheels — how many units of work.")
    severity: Severity
    description: str = Field(max_length=200, description="The work, in a few words.")
    seen: str = Field(max_length=300, description="What in the photo shows the need.")


class Inspection(BaseModel):
    findings: list[Finding] = Field(default_factory=list)


@dataclass(slots=True)
class Reading:
    findings: list[Finding]
    warnings: list[str] = field(default_factory=list)


def verify(inspection: Inspection, photos: int) -> Reading:
    """Keep findings that point at a photo that was sent, once each.

    What the model saw cannot be checked by code — a person confirms every
    line. What can be checked is checked: the photo it names exists, the
    quantity is a count of something, and the same finding is not listed twice.
    """
    kept: list[Finding] = []
    seen: set[tuple[int, str, str, str]] = set()
    warnings: list[str] = []
    for finding in inspection.findings[:30]:
        if not 1 <= finding.photo <= photos:
            warnings.append(f"skipped {finding.description!r}: there is no photo {finding.photo}")
            continue
        key = (finding.photo, finding.area, finding.operation, finding.description.lower())
        if key in seen:
            continue
        seen.add(key)
        kept.append(finding.model_copy(update={"quantity": min(max(finding.quantity, 1), 20)}))
    return Reading(findings=kept, warnings=warnings)


async def inspect(
    *, tenant_id: UUID, photos: list[tuple[bytes, str]], hint: str | None = None
) -> Reading:
    """Read inspection photos into proposed work. One vision call; writes nothing."""
    parts: list[types.Part] = []
    for number, (data, mime_type) in enumerate(photos, start=1):
        parts.append(types.Part.from_text(text=f"Photo {number}:"))
        parts.append(types.Part.from_bytes(data=data, mime_type=mime_type))
    parts.append(
        types.Part.from_text(
            text="List the reconditioning work these photos show."
            + (f"\n\n<untrusted>\n{hint}\n</untrusted>" if hint else "")
        )
    )
    result = await complete(
        TaskKind.VISION,
        tenant_id=tenant_id,
        system=SystemLayers(role=load("inspection")),
        messages=types.Content(role="user", parts=parts),
        output_schema=Inspection,
        trace_name="inspection",
    )
    assert isinstance(result.parsed, Inspection)  # noqa: S101 - schema-constrained
    reading = verify(result.parsed, len(photos))
    log.info(
        "inspection_read",
        photos=len(photos),
        findings=len(reading.findings),
        read=len(result.parsed.findings),
        cost_usd=round(result.cost_usd, 6),
    )
    return reading
