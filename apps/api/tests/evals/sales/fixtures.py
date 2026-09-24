"""A fixed workspace for the copilot eval.

Fixed, not relative: an eval whose inventory changes is an eval whose results
cannot be compared week to week. Same six cars at the same prices, the same
three policy documents, every run.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import asyncpg

from dealerai.ai.embeddings import embed, literal
from dealerai.sales import knowledge

HERE = Path(__file__).parent

#: key -> (make, model, trim, year, price_minor, status, colour, km)
#:
#: One reserved and one sold on purpose: the two ways an inventory guard can
#: catch a draft offering something the dealership cannot sell.
VEHICLES: dict[str, tuple[str, str, str, int, int, str, str, int]] = {
    "land-cruiser": (
        "Toyota",
        "Land Cruiser",
        "4.0 VX",
        2023,
        23500000,
        "available",
        "White",
        18000,
    ),
    "hilux-gr": ("Toyota", "Hilux", "GR Sport", 2023, 16500000, "available", "Black", 24000),
    "hilux-diesel": ("Toyota", "Hilux", "2.8 Diesel", 2022, 12800000, "available", "Silver", 62000),
    "seal-05": ("BYD", "Seal 05", "", 2024, 8900000, "available", "White", 5000),
    "patrol": ("Nissan", "Patrol", "LE", 2022, 21000000, "reserved", "Grey", 41000),
    "x5": ("BMW", "X5", "xDrive40i", 2021, 19000000, "sold", "Blue", 55000),
}

TENANT = uuid.UUID("11111111-0000-4000-8000-0000000000e1")
OWNER = uuid.UUID("11111111-1111-4000-8000-0000000000e1")
CHANNEL_EXTERNAL_ID = "eval-wa-number"


async def build(conn: asyncpg.Connection) -> dict[str, Any]:
    """Tear the workspace down and build it again, identically."""
    await conn.execute("delete from tenants where id = $1", TENANT)
    await conn.execute("delete from auth.users where id = $1", OWNER)

    await conn.execute(
        """insert into tenants (id, slug, name, country, timezone, currency, monthly_ai_budget_usd)
           values ($1, 'eval-motors', 'Pollux Motors', 'AE', 'Asia/Dubai', 'AED', 50)""",
        TENANT,
    )
    await conn.execute("insert into auth.users (id, email) values ($1, 'eval@example.test')", OWNER)
    await conn.execute(
        "insert into memberships (tenant_id, user_id, role) values ($1, $2, 'owner')",
        TENANT,
        OWNER,
    )
    await conn.execute("select app.seed_default_pipeline($1)", TENANT)

    channel_id = await conn.fetchval(
        """insert into channels (tenant_id, platform, external_id, handle, display_name, status)
           values ($1, 'whatsapp', $2, '+971 4 123 4567', 'Pollux Motors', 'connected')
           returning id""",
        TENANT,
        CHANNEL_EXTERNAL_ID,
    )
    for name, category, body in (
        ("price_update", "utility", "Hello {{1}}, the {{2}} is now {{3}}."),
        ("vehicle_available", "utility", "Hello {{1}}, the {{2}} you asked about is available."),
    ):
        await conn.execute(
            """insert into message_templates
                 (tenant_id, channel_id, external_id, name, language, category, status, body)
               values ($1,$2,$3,$4,'en',$5,'approved',$6)""",
            TENANT,
            channel_id,
            f"tpl-{name}",
            name,
            category,
            body,
        )

    vehicles: dict[str, uuid.UUID] = {}
    for key, (make, model, trim, year, price, status, colour, km) in VEHICLES.items():
        vehicles[key] = uuid.UUID(
            str(
                await conn.fetchval(
                    """insert into vehicles (tenant_id, make, model, trim, model_year, price_minor,
                                             currency, status, exterior_color, mileage_km,
                                             vehicle_condition, listed_at)
                       values ($1,$2,$3,$4,$5,$6,'AED',$7,$8,$9,'used', now()) returning id""",
                    TENANT,
                    make,
                    model,
                    trim or None,
                    year,
                    price,
                    status,
                    colour,
                    km,
                )
            )
        )

    await _load_the_policies(conn)
    return {"tenant": TENANT, "owner": OWNER, "channel": channel_id, "vehicles": vehicles}


async def _load_the_policies(conn: asyncpg.Connection) -> None:
    """The same three documents the recall check uses, embedded for real."""
    for path in sorted((HERE / "policies").glob("*.md")):
        pieces = knowledge.chunk(path.read_text("utf-8"))
        vectors = await embed(
            [knowledge.embeddable(piece) for piece in pieces], tenant_id=TENANT, kind="document"
        )
        document_id = await conn.fetchval(
            """insert into documents (tenant_id, kind, title, source, status)
               values ($1, 'export_policy', $2, 'upload', 'ready') returning id""",
            TENANT,
            path.stem.replace("-", " ").title(),
        )
        for piece, vector in zip(pieces, vectors, strict=True):
            await conn.execute(
                """insert into doc_chunks
                     (tenant_id, document_id, chunk_index, content, embedding, meta)
                   values ($1,$2,$3,$4,$5::vector,$6::jsonb)""",
                TENANT,
                document_id,
                piece.index,
                piece.content,
                literal(vector),
                json.dumps({"heading": piece.heading}),
            )


#: A person's name per language. The contacts were "Eval en-human-01" once, a
#: draft greeted one of them by it, and the judge — never told the name — marked
#: it invented, at accuracy 1.
NAMES = {"ar": "Khalid", "en": "Daniel", "fr": "Karim"}


async def a_conversation(
    conn: asyncpg.Connection,
    world: dict[str, Any],
    item: dict[str, Any],
) -> tuple[uuid.UUID, uuid.UUID]:
    """One customer, one thread, with the item's messages in it.

    Returns (conversation_id, the id of the last customer message) — which is
    what `copilot.draft_requested` carries.
    """
    now = datetime.now(UTC)
    contact_id = await conn.fetchval(
        """insert into contacts (tenant_id, full_name, locale, country, owner_id)
           values ($1, $2, $3, $4, $5) returning id""",
        world["tenant"],
        NAMES[item["language"]],
        item["language"],
        {"ar": "AE", "fr": "DZ", "en": "AE"}[item["language"]],
        world["owner"],
    )
    closed = item.get("window") == "closed"
    window = now - timedelta(hours=1) if closed else now + timedelta(hours=23)
    conversation_id = await conn.fetchval(
        """insert into conversations
             (tenant_id, contact_id, channel_id, surface, status, owner_id, assigned_to,
              wa_window_expires_at)
           values ($1,$2,$3,'whatsapp','open',$4,$4,$5) returning id""",
        world["tenant"],
        contact_id,
        world["channel"],
        world["owner"],
        window,
    )
    last_inbound: uuid.UUID | None = None
    for index, message in enumerate(item["messages"]):
        message_id = await conn.fetchval(
            """insert into messages (tenant_id, conversation_id, kind, direction, sender, origin,
                                     type, body, created_at)
               values ($1,$2,'message',$3,$4,$5,'text',$6,$7) returning id""",
            world["tenant"],
            conversation_id,
            message["direction"],
            "customer" if message["direction"] == "in" else "human",
            "customer" if message["direction"] == "in" else "inbox",
            message["text"],
            now - timedelta(minutes=len(item["messages"]) - index),
        )
        if message["direction"] == "in":
            last_inbound = uuid.UUID(str(message_id))
    assert last_inbound is not None, f"{item['id']} has no customer message"
    return uuid.UUID(str(conversation_id)), last_inbound
