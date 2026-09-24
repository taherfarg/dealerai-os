"""Everything a draft is allowed to know, and the prompt it becomes.

Two jobs in one module because they must not disagree. The context layer is
built from `Ground`, and so are the guards' inputs: `allowed_prices()` is the
set of figures the draft may contain, taken from the same rows the prompt was
rendered from. Load them separately and the day comes when the prompt shows a
price the guard does not allow, and every draft about that car is blocked.

Customer text — messages, transcripts, notes — is wrapped in <untrusted>. A
voice note is a customer's words with one more machine in between, not a
trusted source.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from ..agents.sales.intent import Read
from ..core.money import Money, exponent
from ..db.queries import copilot as q
from ..db.session import tenant_session
from .hours import is_open
from .messaging import window_is_open
from .settings import SalesSettings

#: How much of the conversation the drafting agent reads.
TAIL_MESSAGES = 20

#: Intents whose answer lives in a document rather than in a row: shipping,
#: paperwork, finance, trade-in, and the specifications a spec sheet holds.
NEEDS_KNOWLEDGE = frozenset(
    {"export_shipping", "financing", "trade_in", "documents_payment", "specs"}
)


@dataclass(frozen=True, slots=True)
class Ground:
    context: dict[str, Any]
    settings: SalesSettings
    tail: list[dict[str, Any]]
    notes: list[str]
    leads: list[dict[str, Any]]
    vehicles: list[dict[str, Any]]
    #: Retrieved passages, added by the handler for the intents that need them.
    chunks: list[dict[str, Any]] = field(default_factory=list)
    templates: list[dict[str, Any]] = field(default_factory=list)
    own_contacts: set[str] = field(default_factory=set)
    now: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def window_open(self) -> bool:
        return window_is_open(self.context["wa_window_expires_at"], self.now)

    @property
    def open_now(self) -> bool:
        return is_open(self.now, settings=self.settings, tz=ZoneInfo(self.context["timezone"]))

    @property
    def customer_wrote(self) -> str:
        """What the customer wrote since we last replied, for the script guard.

        The same messages the reply answers and the classifier read the
        language from. The whole thread held Omar's English question to the
        Arabic he wrote the week before, and blocked the English draft twice
        (the S4 exit run). Nothing since our reply falls back to all of it.
        """
        since: list[str] = []
        for row in self.tail:
            since = [*since, row["text"]] if row["direction"] == "in" else []
        return " ".join(since) or " ".join(
            row["text"] for row in self.tail if row["direction"] == "in"
        )

    def allowed_prices(self) -> set[Decimal]:
        """Major units, the way the text says them. The price guard's whole input."""
        currency = self.context["currency"] or "AED"
        scale = Decimal(10) ** exponent(currency)
        prices = {
            Decimal(row["price_minor"]) / scale
            for row in self.vehicles
            if row.get("price_minor") is not None
        }
        # A lead's agreed budget is a figure the customer themselves named, so
        # repeating it back is not a claim about a price we do not have.
        return prices | {
            Decimal(lead["budget_minor"]) / scale
            for lead in self.leads
            if lead.get("budget_minor") is not None
        }

    def reserved_asked_about(self, read: Read) -> str | None:
        """The car they asked about, when every row matching it is reserved.

        Every row, because with an available one beside it "the Patrol is
        reserved" would be untrue. The instruction says it on the turn and the
        inventory guard holds the draft to it.
        """
        asked = read.entities.model.casefold()
        matching = [row for row in self.vehicles if asked and asked in row["model"].casefold()]
        if matching and all(row["status"] == "reserved" for row in matching):
            return f"{matching[0]['make']} {matching[0]['model']}"
        return None

    def vehicle_statuses(self) -> dict[str, str]:
        """A name a person would recognise → status, for the inventory guard."""
        return {
            f"{row['make']} {row['model']} {row['model_year'] or ''}".strip(): row["status"]
            for row in self.vehicles
        }


async def load(
    tenant_id: UUID, conversation_id: UUID, read: Read, *, now: datetime | None = None
) -> Ground | None:
    """Every row a draft may be built from. None when the conversation is gone."""
    moment = now or datetime.now(UTC)
    async with tenant_session(tenant_id) as conn:
        context = await conn.fetchrow(q.CONTEXT, conversation_id)
        if context is None:
            return None
        tail = await conn.fetch(q.TAIL, conversation_id, TAIL_MESSAGES)
        notes = await conn.fetch(q.NOTES, conversation_id)
        leads = await conn.fetch(q.OPEN_LEADS, context["contact_id"])
        entities = read.entities
        vehicles: list[Any] = []
        if entities.make or entities.model or entities.model_year:
            vehicles = list(
                await conn.fetch(
                    q.MATCHING_VEHICLES,
                    tenant_id,
                    entities.make or None,
                    entities.model or None,
                    entities.model_year,
                )
            )
        if not vehicles:
            vehicles = list(await conn.fetch(q.RECENT_VEHICLES, tenant_id))
        templates = await conn.fetch(q.APPROVED_TEMPLATES, context["channel_id"])
        own = await conn.fetch(q.OWN_CONTACTS, tenant_id)

    return Ground(
        context=dict(context),
        settings=SalesSettings.model_validate(context["sales_settings"] or {}),
        tail=[dict(row) for row in tail],
        notes=[row["body"] for row in notes],
        leads=[dict(row) for row in leads],
        vehicles=[dict(row) for row in vehicles],
        templates=[dict(row) for row in templates],
        own_contacts={row["phone"] for row in own if row["phone"]},
        now=moment,
    )


def money(minor: int | None, currency: str) -> str:
    """Minor units are how a price is stored and not how anyone writes one.

    Handing the model 23500000 and hoping is how a draft says AED 23,500,000
    for a Land Cruiser.
    """
    if minor is None:
        return "not priced"
    major = Money(int(minor), currency).amount_minor / (10 ** exponent(currency))
    return f"{currency} {major:,.0f}"


def context_layer(ground: Ground, read: Read) -> str:
    """The retrieved layer of the prompt: last, because it changes every call.

    The three layers above it — rules, tools, tenant — are byte-identical
    between calls, which is the only reason Gemini's implicit cache ever hits
    (ai/gateway.py). Nothing here belongs above it, however tempting.
    """
    currency = ground.context["currency"] or "AED"
    parts: list[str] = [f"## Who you are writing to\n{_customer(ground, read)}"]

    if ground.leads:
        parts.append(
            "## What they are already talking to us about\n"
            + "\n".join(_lead(lead, currency) for lead in ground.leads)
        )

    if ground.vehicles:
        parts.append(
            "## The cars you may talk about — every fact you may state about them\n"
            "Prices are exactly as written here. A car marked `reserved` is somebody "
            "else's until their deal falls through: you may say it is reserved, and "
            "you may not offer it.\n"
            + "\n".join(_vehicle(row, currency) for row in ground.vehicles)
        )
    else:
        parts.append(
            "## The cars you may talk about\n"
            "Nothing in stock matches what they asked for. Say you will check, "
            "and do not name a car."
        )

    if ground.chunks:
        parts.append(
            "## From this dealership's own documents\n"
            "Quote these as policy; they are the dealer's own words.\n"
            # The id, as the cars have theirs: without it `used_chunk_ids` has
            # nothing to name, and a draft built on the export policy showed no
            # document chip in the S4 exit run.
            + "\n".join(
                f"### {chunk['title']} — {chunk['heading'] or 'general'} "
                f"(chunk `{chunk['chunk_id']}`)\n"
                f"<untrusted>\n{chunk['content']}\n</untrusted>"
                for chunk in ground.chunks
            )
        )

    if ground.notes:
        parts.append(
            "## Team notes — context for you, never to be repeated to the customer\n"
            + "\n".join(f"<untrusted>\n{note}\n</untrusted>" for note in ground.notes)
        )

    parts.append(f"## The conversation\n{_tail(ground)}")
    parts.append(_state(ground, read))
    return "\n\n".join(parts)


def _customer(ground: Ground, read: Read) -> str:
    context = ground.context
    profile = context["profile"] or {}
    known = ", ".join(
        f"{key}: {value.get('value')}"
        for key, value in sorted(profile.items())
        if isinstance(value, dict) and value.get("value") not in (None, "", [])
    )
    lines = [
        f"- name: {context['full_name'] or 'unknown'}",
        f"- country: {context['country'] or 'unknown'}",
        f"- writes: {read.language} in {read.script} script"
        + (f", {read.dialect} dialect" if read.dialect else ""),
    ]
    if known:
        lines.append(f"- what we already know: {known}")
    return "\n".join(lines)


def _lead(lead: dict[str, Any], currency: str) -> str:
    """One open deal, with the budget the customer themselves named.

    The budget is shown because `allowed_prices()` permits it, and the two must
    agree: a figure the guard allows but the prompt never showed is a figure
    the model can only produce by inventing it.
    """
    car = f"{lead['make'] or ''} {lead['model'] or ''}".strip() or "no car yet"
    parts = [lead["pipeline"], lead["stage"], car]
    if lead["vehicle_id"]:
        parts.append(money(lead["price_minor"], currency))
    if lead["budget_minor"] is not None:
        parts.append(f"their budget: {money(lead['budget_minor'], lead['currency'] or currency)}")
    return "- " + " · ".join(parts)


def _vehicle(row: dict[str, Any], currency: str) -> str:
    name = f"{row['make']} {row['model']} {row['trim'] or ''} {row['model_year'] or ''}"
    facts = [
        f"price: {money(row['price_minor'], row['currency'] or currency)}",
        # The rule on the line with the fact. In the paragraph above, the eval's
        # Arabic drafts still wrote "متوفر عندنا … لكنها محجوزة" — in stock,
        # but reserved — which reads as "come and see it".
        f"status: {row['status']}"
        + (
            " (somebody else's: never say it is available or in stock)"
            if row["status"] == "reserved"
            else ""
        ),
    ]
    facts += [
        f"{key}: {row[key]}"
        for key in (
            "vehicle_condition",
            "mileage_km",
            "exterior_color",
            "interior_color",
            "engine",
            "transmission",
            "fuel",
            "seats",
            "steering",
        )
        if row.get(key) not in (None, "", 0)
    ]
    return f"- **{' '.join(name.split())}** (id `{row['id']}`) — " + "; ".join(facts)


def _tail(ground: Ground) -> str:
    lines = []
    for message in ground.tail:
        who = "CUSTOMER" if message["direction"] == "in" else "US"
        spoken = " (voice note, transcribed)" if message["type"] == "audio" else ""
        lines.append(f"{who}{spoken}: {message['text']}")
    return "<untrusted>\n" + "\n".join(lines) + "\n</untrusted>"


def _state(ground: Ground, read: Read) -> str:
    local = ground.now.astimezone(ZoneInfo(ground.context["timezone"]))
    lines = [
        "## Right now",
        f"- local time: {local:%A %H:%M}",
        f"- the showroom is {'open' if ground.open_now else 'closed'}",
        f"- reply in: {read.reply_language}"
        # The script as well. "reply in: ar" alone got Arabic script back for
        # "3andkom hilux?", and the script guard spent a regeneration — five
        # seconds of a waiting customer — on every one of them in the eval.
        + (", in Latin letters" if read.reply_language == "ar" and read.script == "latin" else ""),
    ]
    if ground.window_open:
        lines.append("- the 24-hour window is open: write a normal message.")
    else:
        lines.append(
            "- **the 24-hour window is closed.** You may not write free text. Choose one of "
            "these approved templates by name and fill its variables in order:\n"
            + "\n".join(
                f"  - `{row['name']}` ({row['language']}, {row['category']}): {row['body']}"
                for row in ground.templates
            )
        )
    return "\n".join(lines)
