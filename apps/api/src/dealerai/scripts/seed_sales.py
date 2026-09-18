"""Local seed data: Pollux Motors with a team, cars and customers.

Run with `npm run db:seed`. Everything it writes is fictional; phone numbers use
an obviously fake block so nobody can message a real person from a demo.

People get stable ids derived from their names, so a local sign-in session
(routes/dev.py) survives a re-seed, and a second run replaces the workspace
instead of colliding with it.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, UUID, uuid5

import asyncpg

from ..config import get_settings

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

#: (name, phone, country, language, local or export)
CUSTOMERS: tuple[tuple[str, str, str, str, str], ...] = (
    ("Omar Al Mazrouei", "+971500000101", "AE", "ar", "local"),
    ("Karim Benali", "+213500000102", "DZ", "fr", "export"),
    ("Youssef El Idrissi", "+212500000103", "MA", "fr", "export"),
    ("James Whitfield", "+971500000104", "AE", "en", "local"),
    ("Mona Fathy", "+201000000105", "EG", "ar", "local"),
)


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
        '{"first_response_target_min": 5, "unassigned_visible_to_sales": true}',
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
    for i, (name, phone, country, language, kind) in enumerate(CUSTOMERS):
        if kind == "export":
            owner = person_id("Salem Bousaid")
        else:
            owner = person_id("Ahmed Nasser" if i % 2 else "Mohamed Riad")
        contact_id = await conn.fetchval(
            """insert into contacts (tenant_id, full_name, locale, country, owner_id, team_id,
                                     last_seen_at)
               values ($1, $2, $3, $4, $5, $6, $7) returning id""",
            TENANT,
            name,
            language,
            country,
            owner,
            teams["export" if kind == "export" else "local"],
            now - timedelta(hours=i),
        )
        await conn.execute(
            """insert into contact_identities (tenant_id, contact_id, kind, value, is_primary)
               values ($1, $2, 'phone', $3, true)""",
            TENANT,
            contact_id,
            phone,
        )
        await conn.execute(
            """insert into contact_identities
                 (tenant_id, contact_id, kind, value, is_primary)
               values ($1, $2, 'whatsapp_user_id', $3, true)""",
            TENANT,
            contact_id,
            f"AE.seed.{i + 1}",
        )
        conversation_id = await conn.fetchval(
            """insert into conversations
                 (tenant_id, contact_id, channel_id, surface, owner_id, team_id,
                  assigned_to, status, last_message_at, last_inbound_at,
                  wa_window_expires_at, waiting_since)
               values ($1,$2,$3,'whatsapp',$4,$5,$4,'open',$6,$6,$7,$6)
               returning id""",
            TENANT,
            contact_id,
            CHANNEL,
            owner,
            teams["export" if kind == "export" else "local"],
            now - timedelta(hours=i),
            now + timedelta(hours=24 - i),
        )
        await conn.execute(
            """insert into messages
                 (tenant_id, conversation_id, direction, sender, origin, body, external_id,
                  status, created_at)
               values ($1,$2,'in','customer','customer',$3,$4,'sent',$5)""",
            TENANT,
            conversation_id,
            "Is this vehicle available?" if language == "en" else "هل السيارة متوفرة؟",
            f"wamid.seed.{i + 1}",
            now - timedelta(hours=i),
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
