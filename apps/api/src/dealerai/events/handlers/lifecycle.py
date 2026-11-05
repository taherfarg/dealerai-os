"""The vehicle lifecycle's events. See docs/lifecycle/README.md."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from uuid import UUID, uuid5

import asyncpg
import structlog

from ...core.money import Money
from ...core.words import Words, named, same
from ...db.session import tenant_session
from ...lifecycle import deals, inbound, numbers, pricing, recon
from ...sales.clock import zone
from ..bus import Event, handler
from .notify import notify

log = structlog.get_logger()

#: Who hears that prices should move, or a repair needs more money: whoever
#: may decide it.
PRICE_DECIDERS = ("owner", "admin")
#: Who hears that a car arrived, or is late: whoever runs the yard.
YARD = ("owner", "admin", "manager")
#: Who hears that published content quotes an old price: whoever can take it down.
CONTENT_OWNERS = ("owner", "admin", "marketer")


async def _members(conn: asyncpg.Connection, tenant_id: UUID, roles: tuple[str, ...]) -> list[UUID]:
    rows = await conn.fetch(
        "select user_id from memberships where tenant_id = $1 and role = any($2::text[])",
        tenant_id,
        list(roles),
    )
    return [row["user_id"] for row in rows]


@handler("pricing.sweep_due")
async def on_pricing_sweep(event: Event) -> None:
    """Every morning, before the brief: every available car, priced against its
    cost, its age and its demand, and a proposal for each that should move.

    One notification for the morning, not one per car. Six proposals is one
    thing to look at, and six interruptions is how a bell gets muted.
    """
    tenant_id = event.tenant_id
    if tenant_id is None:
        raise ValueError("pricing.sweep_due requires a tenant")
    day = str(event.payload.get("date") or "")

    async with tenant_session(tenant_id) as conn, conn.transaction():
        counts = await pricing.sweep(conn, tenant_id)
        if counts["proposed"]:
            n = counts["proposed"]
            for user_id in await _members(conn, tenant_id, PRICE_DECIDERS):
                await notify(
                    conn,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    kind="price_proposed",
                    title=Words(
                        f"{n} price change{'s' if n != 1 else ''} proposed",
                        f"اقتراح تغيير سعر {n} سيارة",
                    ),
                    body=Words(
                        "Cars that have aged past your pricing ladder. Approve or reject each.",
                        "سيارات تجاوزت مدة البقاء في سلّم التسعير. وافق أو ارفض كل اقتراح.",
                    ),
                    entity={"type": "approval_queue", "id": day or "pricing"},
                    dedupe_key=f"price_proposed:{day}",
                )
    log.info("pricing_swept", tenant_id=str(tenant_id), **counts)


async def after_price_change(event: Event) -> None:
    """Content that still quotes the old price.

    Called from the copilot's vehicle.price_changed handler: the bus allows one
    handler per event, and both concerns hang off the same moment. Unpublished
    pieces are stopped; published ones are named to whoever can take them
    down, because nothing here can.
    """
    tenant_id = event.tenant_id
    if tenant_id is None:
        return
    vehicle_id = UUID(str(event.payload["vehicle_id"]))
    after = int(event.payload["after_minor"])
    currency = str(event.payload.get("currency") or "AED")

    async with tenant_session(tenant_id) as conn, conn.transaction():
        found = await pricing.stale_content(conn, vehicle_id, price_minor=after, currency=currency)
        if found["published"]:
            n = len(found["published"])
            price = str(Money(after, currency))
            for user_id in await _members(conn, tenant_id, CONTENT_OWNERS):
                await notify(
                    conn,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    kind="content_stale",
                    title=Words(
                        f"{n} published post{'s' if n != 1 else ''} quote an old price",
                        f"{n} من المنشورات المنشورة تذكر سعرًا قديمًا",
                    ),
                    body=Words(
                        f"The price is now {price}. Take them down or correct them.",
                        f"السعر الآن {price}. احذفها أو صحّحها.",
                    ),
                    entity={"type": "vehicle", "id": str(vehicle_id)},
                    dedupe_key=f"content_stale:{vehicle_id}:{after}",
                )
    if found["stopped"] or found["published"]:
        log.info(
            "stale_content",
            vehicle_id=str(vehicle_id),
            stopped=len(found["stopped"]),
            published=len(found["published"]),
        )


@handler("approval.requested")
async def on_approval_requested(event: Event) -> None:
    """A repair over budget, or an order under the floor, told to whoever
    decides it the moment it is asked — a workshop or a buyer is waiting.

    Every approval emits this; only these two ring a bell here. Price proposals
    are told once a morning by the sweep, and the reviewer's queue for the other
    kinds is M4's (docs/09-implementation-plan.md).
    """
    tenant_id = event.tenant_id
    kind = event.payload.get("kind")
    titles = {
        recon.KIND: Words("A repair needs your approval", "إصلاح ينتظر موافقتك"),
        deals.KIND: Words(
            "An order under the floor needs your approval",
            "طلب بسعر أقل من الحد الأدنى ينتظر موافقتك",
        ),
    }
    if tenant_id is None or kind not in titles:
        return
    approval_id = str(event.payload["approval_id"])
    summary = str(event.payload.get("summary") or "")
    async with tenant_session(tenant_id) as conn, conn.transaction():
        for user_id in await _members(conn, tenant_id, PRICE_DECIDERS):
            await notify(
                conn,
                tenant_id=tenant_id,
                user_id=user_id,
                kind="recon_approval" if kind == recon.KIND else "price_below_floor",
                title=titles[kind],
                # The car, the work and the amounts: numbers and names read the
                # same in either language.
                body=same(summary),
                entity={"type": "approval_queue", "id": approval_id},
                dedupe_key=f"recon_approval:{approval_id}",
            )


@handler("recon.overran")
async def on_recon_overran(event: Event) -> None:
    """A repair came in above its estimate and took the car over budget. The
    money is spent — there is nothing to approve — so the owner is told."""
    tenant_id = event.tenant_id
    if tenant_id is None:
        return
    payload = event.payload
    currency = str(payload.get("currency") or "AED")
    actual = Money(int(payload["actual_minor"]), currency).display()
    estimate = Money(int(payload["estimate_minor"]), currency).display()
    over = Money(int(payload["over_minor"]), currency).display()
    what = str(payload.get("description") or "")
    async with tenant_session(tenant_id) as conn, conn.transaction():
        for user_id in await _members(conn, tenant_id, PRICE_DECIDERS):
            await notify(
                conn,
                tenant_id=tenant_id,
                user_id=user_id,
                kind="recon_overrun",
                title=Words(
                    f"A repair is {over} over budget", f"إصلاح تجاوز الميزانية بمقدار {over}"
                ),
                body=Words(
                    f"{what}: {actual}, estimated at {estimate}.",
                    f"{what}: {actual}، والتقدير كان {estimate}.",
                ),
                entity={"type": "vehicle", "id": str(payload["vehicle_id"])},
                dedupe_key=f"recon_overrun:{payload['item_id']}",
            )


# The papers and the fees, as the bell says them. Two languages, so two names.
PAPERS = {
    "bill_of_sale": ("bill of sale", "فاتورة الشراء"),
    "title": ("title", "سند الملكية"),
    "bill_of_lading": ("bill of lading", "بوليصة الشحن"),
    "customs_declaration": ("customs declaration", "البيان الجمركي"),
    "customs_certificate": ("customs certificate", "شهادة الجمارك"),
    "registration_card": ("registration card", "بطاقة الملكية"),
}
FEES = {
    "purchase": ("purchase", "الشراء"),
    "auction_fee": ("auction fees", "رسوم المزاد"),
    "transport": ("transport", "النقل"),
    "shipping": ("shipping", "الشحن"),
    "customs": ("customs", "الجمارك"),
}


def what_is_missing(found: inbound.Missing) -> Words:
    """The arrival notice's body: what is still missing, or that nothing is."""
    if found.nothing:
        return Words(
            "Its papers are in and its landed cost is complete.",
            "مستنداتها مكتملة وتكلفتها حتى الوصول مكتملة.",
        )
    english: list[str] = []
    arabic: list[str] = []
    if found.documents:
        english.append("papers: " + ", ".join(PAPERS[c][0] for c in found.documents))
        arabic.append("المستندات: " + "، ".join(PAPERS[c][1] for c in found.documents))
    if found.costs:
        english.append("costs: " + ", ".join(FEES[c][0] for c in found.costs))
        arabic.append("التكاليف: " + "، ".join(FEES[c][1] for c in found.costs))
    if found.estimated:
        english.append("still estimates: " + ", ".join(FEES[c][0] for c in found.estimated))
        arabic.append("ما زالت تقديرًا: " + "، ".join(FEES[c][1] for c in found.estimated))
    return Words(
        "Still missing — " + "; ".join(english) + ".", "ما زال ناقصًا — " + "؛ ".join(arabic) + "."
    )


@handler("inbound.arrived")
async def on_inbound_arrived(event: Event) -> None:
    """A car reached the lot. The day it arrives is the day its landed cost
    should be complete, so the notice says what is not — papers, fees, and fees
    still recorded as estimates."""
    tenant_id = event.tenant_id
    if tenant_id is None:
        return
    vehicle_id = UUID(str(event.payload["vehicle_id"]))
    async with tenant_session(tenant_id) as conn, conn.transaction():
        car = await conn.fetchrow(
            "select make, model, model_year from vehicles where id = $1", vehicle_id
        )
        found = await inbound.missing(conn, vehicle_id)
        if car is None or found is None:
            return
        label = " ".join(str(p) for p in (car["model_year"], car["make"], car["model"]) if p)
        for user_id in await _members(conn, tenant_id, YARD):
            await notify(
                conn,
                tenant_id=tenant_id,
                user_id=user_id,
                kind="inbound_arrived",
                title=Words(f"{label} arrived", f"وصلت {named(label)}"),
                body=what_is_missing(found),
                entity={"type": "vehicle", "id": str(vehicle_id)},
                dedupe_key=f"inbound_arrived:{vehicle_id}",
            )
    log.info("inbound_arrived", vehicle_id=str(vehicle_id), complete=found.nothing)


@handler("inbound.sweep_due")
async def on_inbound_sweep(event: Event) -> None:
    """Every morning: the cars past their ETA, in one notice. A shipment that
    slipped a week is found the day it slips, not the day a customer asks."""
    tenant_id = event.tenant_id
    if tenant_id is None:
        raise ValueError("inbound.sweep_due requires a tenant")
    day = str(event.payload.get("date") or "")
    async with tenant_session(tenant_id) as conn, conn.transaction():
        timezone = await conn.fetchval("select timezone from tenants where id = $1", tenant_id)
        today = datetime.now(zone(timezone)).date()
        overdue = await inbound.late(conn, tenant_id, today)
        if overdue:
            n = len(overdue)
            for user_id in await _members(conn, tenant_id, YARD):
                await notify(
                    conn,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    kind="inbound_late",
                    title=Words(
                        f"{n} cars are past their ETA" if n != 1 else "A car is past its ETA",
                        f"{n} من السيارات تجاوزت موعد وصولها المتوقع",
                    ),
                    body=Words(
                        "Ask the carrier for a new date, and tell anyone waiting for one.",
                        "اطلب من شركة الشحن موعدًا جديدًا، وأبلغ من ينتظر السيارة.",
                    ),
                    entity={"type": "inventory", "id": day or "late"},
                    dedupe_key=f"inbound_late:{day}",
                )
    log.info("inbound_swept", tenant_id=str(tenant_id), late=len(overdue))


async def _off_sale(event: Event) -> None:
    """A car that is not for sale any more is not marketed any more.

    Unpublished content about it is archived; published content is named to
    whoever can take it down, because nothing here can. Telling customers who
    asked about the car that it has gone is S7's, and joins this handler then.
    """
    tenant_id = event.tenant_id
    if tenant_id is None:
        return
    vehicle_id = UUID(str(event.payload["vehicle_id"]))
    status = str(event.payload.get("status") or "")
    async with tenant_session(tenant_id) as conn, conn.transaction():
        found = await deals.stop_marketing(conn, vehicle_id, status)
        if found["published"]:
            n = len(found["published"])
            car = await conn.fetchrow(
                "select make, model, model_year from vehicles where id = $1", vehicle_id
            )
            label = (
                " ".join(str(p) for p in (car["model_year"], car["make"], car["model"]) if p)
                if car
                else ""
            )
            state_en, state_ar = {
                "reserved": ("reserved", "محجوزة"),
                "sold": ("sold", "مباعة"),
            }.get(status, ("off sale", "غير معروضة للبيع"))
            for user_id in await _members(conn, tenant_id, CONTENT_OWNERS):
                await notify(
                    conn,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    kind="marketing_stopped",
                    title=Words(
                        f"{n} published posts advertise a car that is {state_en}"
                        if n != 1
                        else f"A published post advertises a car that is {state_en}",
                        f"{n} من المنشورات تعلن عن سيارة {state_ar}",
                    ),
                    body=Words(
                        f"{label}. Take them down or mark the car as sold in them.",
                        f"{named(label)}. احذفها أو اذكر فيها أن السيارة بيعت.",
                    ),
                    entity={"type": "vehicle", "id": str(vehicle_id)},
                    dedupe_key=f"marketing_stopped:{vehicle_id}:{status}",
                )
    if found["stopped"] or found["published"]:
        log.info(
            "marketing_stopped",
            vehicle_id=str(vehicle_id),
            status=status,
            stopped=len(found["stopped"]),
            published=len(found["published"]),
        )


@handler("vehicle.sold")
async def on_vehicle_sold(event: Event) -> None:
    await _off_sale(event)


@handler("vehicle.status_changed")
async def on_vehicle_status_changed(event: Event) -> None:
    await _off_sale(event)


# --------------------------------------------------------------------------
# after the sale — docs/lifecycle/README.md § L8
# --------------------------------------------------------------------------

#: When to ask a buyer how the car is: a week after a local sale, and six weeks
#: after an export — sea freight from Jebel Ali is two to six (pollux.md).
CHECK_IN_AFTER_DAYS = {"local": 7, "export": 42}
#: In the morning where the showroom is, not whenever the last payment landed.
CHECK_IN_AT = time(10, 0)

_SOLD_ORDER = """
select o.id, o.status, o.purchase_type, o.completed_at, o.created_by, o.lead_id,
       coalesce(o.contact_id, l.contact_id) as contact_id, l.owner_id as lead_owner,
       v.model_year, v.make, v.model, v.trim, t.timezone
  from sale_orders o
  join vehicles v on v.id = o.vehicle_id
  join tenants t on t.id = o.tenant_id
  left join leads l on l.id = o.lead_id
 where o.id = $1
"""


def check_in_title(car: str, locale: str | None) -> str:
    words = Words(
        f"After-sale check-in: how is the {car}? Ask for a review or a referral.",
        f"متابعة ما بعد البيع: كيف حال {named(car)}؟ اطلب تقييمًا أو ترشيحًا.",
    )
    return words.ar if locale == "ar" else words.en


@handler("order.completed")
async def on_order_completed(event: Event) -> None:
    """A sold car books one check-in for the salesperson who owns the buyer —
    the lead's owner, or whoever made the order. Its id is the order's, so a
    retried event books nothing twice."""
    if event.tenant_id is None:
        raise ValueError("order.completed requires a tenant")
    order_id = UUID(str(event.payload["order_id"]))
    async with tenant_session(event.tenant_id) as conn:
        order = await conn.fetchrow(_SOLD_ORDER, order_id)
        if order is None or order["status"] != "completed" or order["completed_at"] is None:
            return
        members = {
            row["user_id"]
            for row in await conn.fetch(
                "select user_id from memberships where tenant_id = $1", event.tenant_id
            )
        }
        assignee = next(
            (who for who in (order["lead_owner"], order["created_by"]) if who in members), None
        )
        if assignee is None:
            log.info("check_in_nobody", order_id=str(order_id))
            return
        tz = zone(order["timezone"])
        day = order["completed_at"].astimezone(tz).date() + timedelta(
            days=CHECK_IN_AFTER_DAYS[order["purchase_type"]]
        )
        locale = await conn.fetchval("select locale from profiles where id = $1", assignee)
        car = numbers.label(order)
        await conn.execute(
            """insert into tasks (id, tenant_id, title, kind, due_at, assignee_id, contact_id,
                                  lead_id, source)
               values ($1, $2, $3, 'follow_up', $4, $5, $6, $7, 'rule')
               on conflict (id) do nothing""",
            uuid5(order_id, "check-in"),
            event.tenant_id,
            check_in_title(car, locale),
            datetime.combine(day, CHECK_IN_AT, tzinfo=tz),
            assignee,
            order["contact_id"],
            order["lead_id"],
        )
