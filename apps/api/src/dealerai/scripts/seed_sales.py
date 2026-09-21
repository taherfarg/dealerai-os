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

    # The board a workspace gets on creation. The tenant above is inserted
    # directly rather than through app.create_tenant_with_owner, so the seed has
    # to ask for it — and a workspace whose first lead fails is a broken one.
    await conn.execute("select app.seed_default_pipeline($1)", TENANT)

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
                  wa_window_expires_at, waiting_since, sla_due_at)
               values ($1,$2,$3,'whatsapp',$4,$5,$4,$6,$7,$8,$9,$10,$11)
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
        )
        conversations[customer.name] = conversation_id

        for n, (at, direction, body) in enumerate(said):
            spoken = body is None
            await conn.execute(
                """insert into messages
                     (tenant_id, conversation_id, kind, type, direction, sender, origin,
                      author_user_id, body, media, transcript, external_id, status, created_at)
                   values ($1,$2,'message',$3,$4,$5,$6,$7,$8,$9::jsonb,$10::jsonb,$11,$12,$13)""",
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
        f"{len(CUSTOMERS)} customers, {len(CUSTOMERS)} conversations"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(seed()))
