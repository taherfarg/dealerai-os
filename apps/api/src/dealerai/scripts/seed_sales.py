"""Local seed data: Pollux Motors with a team, cars and customers.

Run with `npm run db:seed`. Everything it writes is fictional; phone numbers use
an obviously fake block so nobody can message a real person from a demo.

People get stable ids derived from their names, so a local sign-in session
(routes/dev.py) survives a re-seed, and a second run replaces the workspace
instead of colliding with it.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import NamedTuple
from uuid import NAMESPACE_URL, UUID, uuid5

import asyncpg

from ..config import get_settings
from ..media.storage import object_path, upload

TENANT = UUID("11111111-0000-4000-8000-000000000001")
TENANT_SLUG = "pollux-motors"
CHANNEL = UUID("11111111-0000-4000-8000-000000000002")
PHONE_NUMBER_ID = "pollux-local-phone"
WABA_ID = "pollux-local-waba"
_PEOPLE_NS = uuid5(NAMESPACE_URL, "dealerai-os/seed/people")

#: (full name, role, languages, team: "local" | "export" | "both" | None)
PEOPLE: tuple[tuple[str, str, tuple[str, ...], str | None], ...] = (
    ("Khalid Al Suwaidi", "owner", ("ar", "en"), None),
    ("Sara Mansour", "manager", ("ar", "en"), "both"),
    ("Ahmed Nasser", "sales", ("ar", "en"), "local"),
    ("Mohamed Riad", "sales", ("ar", "en"), "local"),
    ("Salem Bousaid", "sales", ("ar", "fr", "en"), "export"),
)

#: (make, model, model year, price in fils, exterior colour) — sample prices
VEHICLES: tuple[tuple[str, str, int, int, str], ...] = (
    ("Toyota", "Hilux GR Sport", 2025, 16500000, "Black"),
    ("Toyota", "Hilux 2.8 Diesel", 2026, 12800000, "White"),
    ("Toyota", "Land Cruiser 4.0", 2024, 23500000, "Pearl"),
    ("BYD", "Seal 05", 2025, 8900000, "Blue"),
    ("BYD", "Leopard 7 Ultra", 2026, 21500000, "Black"),
    ("Changan", "X5 Plus", 2026, 7600000, "Grey"),
)

#: Pollux sells two ways, so it has two boards ([00](../../docs/sales/00-prd.md) § 5).
#: Each needs exactly one won stage and somewhere to put a lost lead.
BOARDS: tuple[tuple[str, bool, tuple[tuple[str, str], ...]], ...] = (
    (
        "Local sale",
        True,
        (
            ("New", "open"),
            ("Contacted", "open"),
            ("Qualified", "open"),
            ("Appointment", "open"),
            ("Negotiation", "open"),
            ("Won", "won"),
            ("Lost", "lost"),
        ),
    ),
    (
        "Export",
        False,
        (
            ("Enquiry", "open"),
            ("Quoted", "open"),
            ("Documents", "open"),
            ("Shipping", "open"),
            ("Won", "won"),
            ("Lost", "lost"),
        ),
    ),
)


class Deal(NamedTuple):
    """A lead on one of the boards.

    `score` is the sum of its signals' points — the drawer recomputes the
    reasons from the signals, so a stored score that disagrees with them would
    be visible on screen.
    """

    customer: str
    board: str
    stage: str
    vehicle: str
    budget_minor: int
    score: int
    band: str
    signals: tuple[str, ...]
    lost_reason: str | None = None
    #: How long ago it entered its stage, in days.
    days_in_stage: int = 0


DEALS: tuple[Deal, ...] = (
    Deal(
        "Omar Al Mazrouei",
        "Local sale",
        "Negotiation",
        "Land Cruiser 4.0",
        23500000,
        80,
        "hot",
        (
            "asked_price",
            "asked_availability",
            "negotiating_specific_car",
            "requested_visit_or_test_drive",
            "shared_id_or_asked_payment_details",
            "responsive",
        ),
        days_in_stage=2,
    ),
    Deal(
        "Mona Fathy",
        "Local sale",
        "Qualified",
        "Land Cruiser 4.0",
        23500000,
        20,
        "cold",
        ("asked_price", "asked_availability"),
        days_in_stage=1,
    ),
    Deal(
        "James Whitfield",
        "Local sale",
        "New",
        "Hilux GR Sport",
        16500000,
        10,
        "cold",
        ("asked_availability",),
    ),
    Deal(
        "Karim Benali",
        "Export",
        "Quoted",
        "Hilux 2.8 Diesel",
        12800000,
        45,
        "warm",
        (
            "asked_price",
            "asked_availability",
            "asked_export_or_documents",
            "gave_budget_or_timeline_30d",
            "responsive",
        ),
        days_in_stage=3,
    ),
    Deal(
        "Youssef El Idrissi",
        "Export",
        "Won",
        "X5 Plus",
        7600000,
        75,
        "hot",
        (
            "asked_price",
            "asked_export_or_documents",
            "gave_budget_or_timeline_30d",
            "negotiating_specific_car",
            "shared_id_or_asked_payment_details",
            "responsive",
        ),
        days_in_stage=6,
    ),
    Deal(
        "Omar Al Mazrouei",
        "Local sale",
        "Lost",
        "Seal 05",
        8900000,
        25,
        "cold",
        ("asked_price", "asked_availability", "responsive"),
        lost_reason="Bought a used Prado from another dealer",
        days_in_stage=9,
    ),
)


class Chore(NamedTuple):
    title: str
    assignee: str
    customer: str | None
    kind: str
    #: Hours from now; negative is overdue.
    due_in_hours: float
    done: bool = False


CHORES: tuple[Chore, ...] = (
    Chore("Send Karim the export quote", "Salem Bousaid", "Karim Benali", "todo", -26),
    Chore("Call Omar about the passport copy", "Ahmed Nasser", "Omar Al Mazrouei", "call", 2),
    Chore("Book the Land Cruiser inspection", "Ahmed Nasser", "Mona Fathy", "meeting", 72),
    Chore("Chase Mona for the deposit", "Ahmed Nasser", "Mona Fathy", "follow_up", -30, done=True),
)

#: What the AI inferred and what a person answered, on the same two customers —
#: so the panel shows both markers the first time anybody opens it.
PROFILES: dict[str, dict[str, tuple[object, str]]] = {
    "Omar Al Mazrouei": {
        "interest": ("Land Cruiser 4.0, white", "ai"),
        "budget": ({"amount_minor": 23500000, "currency": "AED"}, "ai"),
        "purchase_type": ("local", "human"),
        "timeline": ("This month", "ai"),
    },
    "Karim Benali": {
        "purchase_type": ("export", "human"),
        "destination": ("DZ", "human"),
        "payment": ("finance", "ai"),
        "objections": (["Shipping cost", "Customs paperwork"], "ai"),
    },
}

#: Minutes a customer may wait for a first reply before the inbox says so.
TARGET_MIN = 5


class Customer(NamedTuple):
    """One customer, and the state their conversation is in."""

    name: str
    phone: str
    country: str
    language: str
    team: str
    #: The salesperson's full name, or None to leave it in the unassigned queue.
    owner: str | None
    #: What they said first.
    opening: str
    #: What we said back, if anyone did.
    reply: str | None = None
    status: str = "open"
    #: Minutes they have been waiting for a reply; None means they got one.
    waiting_min: float | None = None
    #: Whether the last thing they sent was a voice note.
    voice: bool = False


#: A Monday morning: one customer missed, one about to be, one nobody has
#: taken, one answered and one closed — so the inbox has something to show the
#: first time it is opened, and so does every screen S3 adds to it.
#:
#: Re-seed before a demo. The "due soon" row becomes a missed one a couple of
#: minutes later, which is the product working rather than the seed rotting.
CUSTOMERS: tuple[Customer, ...] = (
    Customer(
        "Omar Al Mazrouei",
        "+971500000101",
        "AE",
        "ar",
        "local",
        "Ahmed Nasser",
        "السلام عليكم، عندكم هايلكس ٢٠٢٦ ديزل؟",
        waiting_min=22,
    ),
    Customer(
        "Karim Benali",
        "+213500000102",
        "DZ",
        "fr",
        "export",
        "Salem Bousaid",
        "Le prix pour Oran, tout compris ?",
        reply="Bonjour Karim — je vous envoie le total avec le transport aujourd'hui.",
    ),
    Customer(
        "Youssef El Idrissi",
        "+212500000103",
        "MA",
        "fr",
        "export",
        "Salem Bousaid",
        "Merci, j'ai acheté ailleurs.",
        reply="Merci de nous avoir dit, Youssef. À la prochaine.",
        status="closed",
    ),
    Customer(
        "James Whitfield",
        "+971500000104",
        "AE",
        "en",
        "local",
        None,
        "Is the Hilux GR Sport still available?",
        waiting_min=1,
    ),
    Customer(
        "Mona Fathy",
        "+201000000105",
        "EG",
        "ar",
        "local",
        "Ahmed Nasser",
        "مساء الخير، عندكم لاند كروزر ٢٠٢٤؟",
        reply="مساء النور يا مونا. عندنا لاند كروزر ٤.٠ لؤلؤي — أبعتلك التفاصيل.",
        waiting_min=TARGET_MIN - 1.5,
        voice=True,
    ),
)

#: What the seeded voice note says, as the transcriber would have heard it.
VOICE_NOTE = "هل لاند كروزر الأبيض ما زالت متوفرة؟ وكم أفضل سعر عندكم؟"


def _stages_of(board: str) -> tuple[tuple[str, str], ...]:
    return next(stages for name, _, stages in BOARDS if name == board)


def person_id(full_name: str) -> UUID:
    """Stable across re-seeds, so a dev session survives `npm run db:seed`."""
    return uuid5(_PEOPLE_NS, full_name)


def person_email(full_name: str) -> str:
    return full_name.split()[0].lower() + "@pollux.test"


async def _seed(conn: asyncpg.Connection) -> None:
    # Replace, never collide: the tenant cascades to memberships, teams and
    # customers; the people cascade to their profiles.
    await conn.execute("delete from tenants where id = $1", TENANT)
    await conn.execute(
        "delete from auth.users where id = any($1::uuid[])",
        [person_id(name) for name, *_ in PEOPLE],
    )

    await conn.execute(
        """insert into tenants (id, slug, name, timezone, currency, locales, sales_settings)
           values ($1, $2, 'Pollux Motors', 'Asia/Dubai', 'AED', '{en,ar,fr}', $3::jsonb)""",
        TENANT,
        TENANT_SLUG,
        json.dumps({"first_response_target_min": TARGET_MIN, "unassigned_visible_to_sales": True}),
    )

    # Pollux's own boards rather than the default one every new workspace gets:
    # this dealership sells locally and exports, and the two are different work.
    boards: dict[str, dict[str, UUID]] = {}
    for position, (board_name, is_default, stages) in enumerate(BOARDS):
        pipeline_id = await conn.fetchval(
            """insert into pipelines (tenant_id, name, position, is_default)
               values ($1, $2, $3, $4) returning id""",
            TENANT,
            board_name,
            position,
            is_default,
        )
        boards[board_name] = {}
        for stage_position, (stage_name, category) in enumerate(stages):
            boards[board_name][stage_name] = await conn.fetchval(
                """insert into pipeline_stages (tenant_id, pipeline_id, name, position, category)
                   values ($1, $2, $3, $4, $5) returning id""",
                TENANT,
                pipeline_id,
                stage_name,
                stage_position,
                category,
            )

    teams: dict[str, UUID] = {}
    for key, name in (("local", "Local sales"), ("export", "Export")):
        teams[key] = await conn.fetchval(
            "insert into teams (tenant_id, name) values ($1, $2) returning id", TENANT, name
        )

    for full_name, role, languages, team in PEOPLE:
        user_id = person_id(full_name)
        email = person_email(full_name)
        await conn.execute("insert into auth.users (id, email) values ($1, $2)", user_id, email)
        await conn.execute(
            "insert into profiles (id, full_name, email) values ($1, $2, $3)",
            user_id,
            full_name,
            email,
        )
        await conn.execute(
            """insert into memberships (tenant_id, user_id, role, languages)
               values ($1, $2, $3, $4)""",
            TENANT,
            user_id,
            role,
            list(languages),
        )
        member_of = ("local", "export") if team == "both" else ((team,) if team else ())
        for key in member_of:
            await conn.execute(
                "insert into team_members (tenant_id, team_id, user_id) values ($1, $2, $3)",
                TENANT,
                teams[key],
                user_id,
            )

    for make, model, model_year, price_minor, colour in VEHICLES:
        await conn.execute(
            """insert into vehicles (tenant_id, make, model, model_year, price_minor,
                                     exterior_color, status, listed_at)
               values ($1, $2, $3, $4, $5, $6, 'available', now() - interval '40 days')""",
            TENANT,
            make,
            model,
            model_year,
            price_minor,
            colour,
        )

    await conn.execute(
        """insert into channels
             (id, tenant_id, platform, external_id, account_id, display_name, handle,
              mode, credentials)
           values ($1,$2,'whatsapp',$3,$4,'Pollux WhatsApp','+971 50 000 0000',
                   'coexistence','{"provider":"mock"}'::jsonb)""",
        CHANNEL,
        TENANT,
        PHONE_NUMBER_ID,
        WABA_ID,
    )
    await conn.executemany(
        """insert into message_templates
             (tenant_id, channel_id, external_id, name, language, category, status,
              body, variables)
           values ($1,$2,$3,'vehicle_available',$4,'utility','approved',$5,'{1,2}')""",
        [
            (TENANT, CHANNEL, f"seed-template-{language}", language, body)
            for language, body in (
                ("en_US", "The {{1}} is available for {{2}}."),
                ("ar", "السيارة {{1}} متوفرة بسعر {{2}}."),
                ("fr", "Le véhicule {{1}} est disponible à {{2}}."),
            )
        ],
    )

    now = datetime.now(UTC)
    # No local object store means no voice note; the rest of the queue is still
    # worth looking at, so this is not a reason to refuse to seed.
    stored_voice = await _store_voice_note() if get_settings().storage_dir else None
    conversations: dict[str, UUID] = {}
    contacts: dict[str, UUID] = {}
    #: The message a profile field can point at as its evidence.
    first_messages: dict[str, UUID] = {}
    voice_at: datetime | None = None

    for i, customer in enumerate(CUSTOMERS):
        owner = person_id(customer.owner) if customer.owner else None
        team_id = teams[customer.team]
        contact_id = await conn.fetchval(
            """insert into contacts (tenant_id, full_name, locale, country, owner_id, team_id,
                                     last_seen_at)
               values ($1, $2, $3, $4, $5, $6, $7) returning id""",
            TENANT,
            customer.name,
            customer.language,
            customer.country,
            owner,
            team_id,
            now - timedelta(hours=i),
        )
        await conn.execute(
            """insert into contact_identities (tenant_id, contact_id, kind, value, is_primary)
               values ($1, $2, 'phone', $3, true)""",
            TENANT,
            contact_id,
            customer.phone,
        )
        await conn.execute(
            """insert into contact_identities
                 (tenant_id, contact_id, kind, value, is_primary)
               values ($1, $2, 'whatsapp_user_id', $3, true)""",
            TENANT,
            contact_id,
            f"AE.seed.{i + 1}",
        )

        waiting_since = (
            now - timedelta(minutes=customer.waiting_min)
            if customer.waiting_min is not None
            else None
        )
        # An answered conversation started earlier in the day; an unanswered one
        # started when the customer wrote, which is what the timer counts from.
        opened_at = now - timedelta(hours=i + 1) if customer.reply else (waiting_since or now)
        #: (when, direction, what was said — None for the voice note)
        said: list[tuple[datetime, str, str | None]] = [(opened_at, "in", customer.opening)]
        if customer.reply:
            said.append((opened_at + timedelta(minutes=6), "out", customer.reply))
        if customer.voice and waiting_since:
            voice_at = waiting_since
            said.append((waiting_since, "in", None))

        conversation_id = await conn.fetchval(
            """insert into conversations
                 (tenant_id, contact_id, channel_id, surface, owner_id, team_id,
                  assigned_to, status, last_message_at, last_inbound_at,
                  wa_window_expires_at, waiting_since, sla_due_at, first_response_at)
               values ($1,$2,$3,'whatsapp',$4,$5,$4,$6,$7,$8,$9,$10,$11,$12)
               returning id""",
            TENANT,
            contact_id,
            CHANNEL,
            owner,
            team_id,
            customer.status,
            said[-1][0],
            max(at for at, direction, _ in said if direction == "in"),
            now + timedelta(hours=24 - i),
            waiting_since,
            waiting_since + timedelta(minutes=TARGET_MIN) if waiting_since else None,
            # When somebody answered: the number My day shows as the median.
            next((at for at, direction, _ in said if direction == "out"), None),
        )
        conversations[customer.name] = conversation_id
        contacts[customer.name] = contact_id

        for n, (at, direction, body) in enumerate(said):
            spoken = body is None
            message_id = await conn.fetchval(
                """insert into messages
                     (tenant_id, conversation_id, kind, type, direction, sender, origin,
                      author_user_id, body, media, transcript, external_id, status, created_at)
                   values ($1,$2,'message',$3,$4,$5,$6,$7,$8,$9::jsonb,$10::jsonb,$11,$12,$13)
                   returning id""",
                TENANT,
                conversation_id,
                "audio" if spoken else "text",
                direction,
                "customer" if direction == "in" else "human",
                "customer" if direction == "in" else "inbox",
                None if direction == "in" else owner,
                body,
                json.dumps(
                    [
                        {
                            "status": "ready",
                            "storage_path": stored_voice,
                            "mime": "audio/ogg",
                            "size": 9620,
                            "duration_s": 7,
                        }
                    ]
                    if spoken and stored_voice
                    else []
                ),
                json.dumps({"text": VOICE_NOTE, "language": "ar"}) if spoken else None,
                f"wamid.seed.{i + 1}.{n + 1}",
                "sent" if direction == "in" else "delivered",
                at,
            )
            if direction == "in" and customer.name not in first_messages:
                first_messages[customer.name] = message_id

    # ------------------------------------------------------------------
    # What we know about them, and who said so
    # ------------------------------------------------------------------
    for name, fields in PROFILES.items():
        profile = {
            key: {
                "value": value,
                "source": source,
                # An AI value points at the message it was inferred from; the
                # panel's marker is a link to it.
                "evidence_message_id": (
                    str(first_messages[name]) if source == "ai" and name in first_messages else None
                ),
                "updated_at": now.isoformat(),
            }
            for key, (value, source) in fields.items()
        }
        await conn.execute(
            """update contacts set profile = $2::jsonb, profile_updated_at = $3
                where id = $1""",
            contacts[name],
            json.dumps(profile),
            now,
        )

    # ------------------------------------------------------------------
    # The board: something in most columns, one won and one lost
    # ------------------------------------------------------------------
    vehicles = {
        row["model"]: row["id"]
        for row in await conn.fetch("select id, model from vehicles where tenant_id = $1", TENANT)
    }
    for deal in DEALS:
        stage_id = boards[deal.board][deal.stage]
        entered = now - timedelta(days=deal.days_in_stage)
        lead_id = await conn.fetchval(
            """insert into leads (tenant_id, contact_id, conversation_id, pipeline_id, stage_id,
                                  stage_entered_at, owner_id, team_id, vehicle_id, budget_minor,
                                  currency, score, intent_band, score_signals, lost_reason, source,
                                  created_at)
               values ($1,$2,$3,(select pipeline_id from pipeline_stages where id = $4),$4,$5,
                       (select owner_id from contacts where id = $2),
                       (select team_id from contacts where id = $2),
                       $6,$7,'AED',$8,$9,$10::jsonb,$11,'whatsapp',$12)
               returning id""",
            TENANT,
            contacts[deal.customer],
            conversations[deal.customer],
            stage_id,
            entered,
            vehicles.get(deal.vehicle),
            deal.budget_minor,
            deal.score,
            deal.band,
            json.dumps(
                [
                    {
                        "signal": signal,
                        "evidence_message_id": str(first_messages.get(deal.customer))
                        if deal.customer in first_messages
                        else None,
                    }
                    for signal in deal.signals
                ]
            ),
            deal.lost_reason,
            entered - timedelta(days=2),
        )
        # Where it has been: the drawer reads this, and a lead that arrived
        # already in Negotiation with no history looks like a bug.
        if deal.stage not in ("New", "Enquiry"):
            first_open = next(
                name for name, category in _stages_of(deal.board) if category == "open"
            )
            await conn.execute(
                """insert into activities (tenant_id, lead_id, contact_id, kind, body, meta,
                                           actor_type, actor_id, occurs_at)
                   values ($1,$2,$3,'stage_change',$4,$5::jsonb,'user',$6,$7)""",
                TENANT,
                lead_id,
                contacts[deal.customer],
                f"{first_open} → {deal.stage}",
                json.dumps({"to": str(stage_id)}),
                str(person_id("Ahmed Nasser")),
                entered,
            )

    # ------------------------------------------------------------------
    # A day with something already late in it
    # ------------------------------------------------------------------
    for chore in CHORES:
        await conn.execute(
            """insert into tasks (tenant_id, title, kind, due_at, status, completed_at,
                                  assignee_id, created_by, contact_id, conversation_id)
               values ($1,$2,$3,$4,$5,$6,$7,$7,$8,$9)""",
            TENANT,
            chore.title,
            chore.kind,
            now + timedelta(hours=chore.due_in_hours),
            "done" if chore.done else "open",
            now - timedelta(hours=1) if chore.done else None,
            person_id(chore.assignee),
            contacts.get(chore.customer or ""),
            conversations.get(chore.customer or ""),
        )

    # ------------------------------------------------------------------
    # The duplicate, so the merge dialog has something real to merge
    # ------------------------------------------------------------------
    duplicate = await conn.fetchval(
        """insert into contacts (tenant_id, full_name, locale, country, team_id, last_seen_at)
           values ($1, 'Omar Al Mazrouei', 'ar', 'AE', $2, $3) returning id""",
        TENANT,
        teams["local"],
        now - timedelta(days=3),
    )
    await conn.execute(
        """insert into contact_identities (tenant_id, contact_id, kind, value, is_primary)
           values ($1, $2, 'phone', '+971500000201', true)""",
        TENANT,
        duplicate,
    )

    # Two people, two different unread counts, because a manager's view of the
    # queue is not a salesperson's: Sara has looked at the missed conversation
    # and Ahmed has not, and Ahmed has read Mona's thread up to her voice note.
    reads = [("Sara Mansour", conversations["Omar Al Mazrouei"], now)]
    if voice_at:
        reads.append(("Ahmed Nasser", conversations["Mona Fathy"], voice_at - timedelta(minutes=1)))
    for full_name, conversation_id, read_at in reads:
        await conn.execute(
            """insert into conversation_reads (tenant_id, conversation_id, user_id, last_read_at)
               values ($1, $2, $3, $4)""",
            TENANT,
            conversation_id,
            person_id(full_name),
            read_at,
        )


async def _store_voice_note() -> str:
    """The sample voice note, in the local object store, so the thread can play it."""
    sample = Path(__file__).parents[1] / "connectors" / "samples" / "voice-note.ogg"
    return await upload(
        object_path(TENANT, "messages", "ogg"), sample.read_bytes(), content_type="audio/ogg"
    )


async def seed() -> int:
    settings = get_settings()
    if settings.env != "local":
        # Refuse before connecting: the first statement deletes a tenant.
        print(f"refusing to seed: ENV is {settings.env!r}, expected 'local'", file=sys.stderr)
        return 1

    conn = await asyncpg.connect(settings.migration_dsn)
    try:
        async with conn.transaction():
            await _seed(conn)
    finally:
        await conn.close()
    print(
        f"seeded {TENANT_SLUG}: {len(PEOPLE)} people, {len(VEHICLES)} vehicles, "
        f"{len(CUSTOMERS)} customers, {len(CUSTOMERS)} conversations, "
        f"{len(BOARDS)} boards, {len(DEALS)} leads, {len(CHORES)} tasks"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(seed()))
