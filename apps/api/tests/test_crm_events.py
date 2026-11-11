"""What the queue does after a customer changes hands."""

from __future__ import annotations

import uuid

import asyncpg

from conftest import TENANT_A, USER_A, USER_B
from dealerai.core.words import named
from dealerai.events.bus import Event
from dealerai.events.handlers import crm


def _event(contact_id: uuid.UUID, owner: uuid.UUID, actor: uuid.UUID | None) -> Event:
    return Event(
        id=1,
        tenant_id=TENANT_A,
        event_type="contact.reassigned",
        payload={
            "contact_id": str(contact_id),
            "owner_id": str(owner),
            "actor_id": str(actor) if actor else None,
        },
        attempts=1,
        dedupe_key=None,
    )


async def _a_customer(conn: asyncpg.Connection, name: str = "Omar Al Mazrouei") -> uuid.UUID:
    contact = await conn.fetchval(
        "insert into contacts (tenant_id, full_name) values ($1, $2) returning id",
        TENANT_A,
        name,
    )
    return uuid.UUID(str(contact))


async def _told(conn: asyncpg.Connection, user_id: uuid.UUID) -> list[asyncpg.Record]:
    return await conn.fetch(  # type: ignore[no-any-return]
        """select kind, title, body, href, entity from notifications
            where tenant_id = $1 and user_id = $2 order by created_at""",
        TENANT_A,
        user_id,
    )


async def test_the_new_owner_is_told_where_to_find_them(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    contact = await _a_customer(su)
    await su.execute(
        "insert into profiles (id, full_name, email) values ($1, 'Sara Mansour', 'sara@x.test')",
        USER_A,
    )

    await crm.on_contact_reassigned(_event(contact, USER_B, USER_A))

    [told] = await _told(su, USER_B)
    assert told["title"] == f"{named('Omar Al Mazrouei')} is yours now"
    assert told["body"] == f"Handed over by {named('Sara Mansour')}"
    assert told["href"] == f"/customers/{contact}", "the bell has to land on the customer"
    assert told["kind"] == "contact_assigned"


async def test_handing_the_same_customer_over_twice_is_one_piece_of_news(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    """The queue retries; a person should not be told twice for one handover."""
    contact = await _a_customer(su)

    await crm.on_contact_reassigned(_event(contact, USER_B, None))
    await crm.on_contact_reassigned(_event(contact, USER_B, None))

    assert len(await _told(su, USER_B)) == 1


async def test_a_customer_deleted_before_the_handler_ran_is_not_an_error(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    """A merge can delete the row between the write and its event. Retrying
    five times and dead-lettering would be noise about nothing."""
    await crm.on_contact_reassigned(_event(uuid.uuid4(), USER_B, USER_A))

    assert await _told(su, USER_B) == []
