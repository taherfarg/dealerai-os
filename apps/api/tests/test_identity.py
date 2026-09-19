"""WhatsApp identities resolve to exactly one customer, even under concurrency."""

from __future__ import annotations

import asyncio
import uuid

import asyncpg
import pytest

from conftest import TENANT_A
from dealerai.db.session import tenant_session
from dealerai.sales.identity import resolve_whatsapp_identity


async def _resolve(**overrides: object) -> uuid.UUID:
    args: dict[str, object] = {
        "tenant_id": TENANT_A,
        "bsuid": "AE.13491208655302741918",
        "wa_id": "971500009999",
        "profile_name": "Karim Benali",
        "team_id": None,
    }
    args.update(overrides)
    async with tenant_session(TENANT_A) as conn:
        return await resolve_whatsapp_identity(conn, **args)  # type: ignore[arg-type]


async def test_a_bsuid_resolves_before_the_phone(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    contact_id = await _resolve()
    same = await _resolve(wa_id="971500008888", profile_name="Karim B.")
    assert same == contact_id
    assert (
        await su.fetchval(
            """select count(*) from contact_identities
               where tenant_id = $1 and contact_id = $2 and kind = 'whatsapp_user_id'""",
            TENANT_A,
            contact_id,
        )
        == 1
    )


async def test_a_known_phone_gets_the_new_bsuid(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    contact_id = await su.fetchval(
        "insert into contacts (tenant_id, full_name) values ($1, 'Known phone') returning id",
        TENANT_A,
    )
    await su.execute(
        """insert into contact_identities (tenant_id, contact_id, kind, value, is_primary)
           values ($1, $2, 'phone', '+971500007777', true)""",
        TENANT_A,
        contact_id,
    )
    resolved = await _resolve(bsuid="AE.new-user", wa_id="971500007777")
    assert resolved == contact_id
    assert await su.fetchval(
        """select exists(select 1 from contact_identities
             where contact_id = $1 and kind = 'whatsapp_user_id' and value = 'AE.new-user')""",
        contact_id,
    )


async def test_a_customer_with_no_phone_resolves_by_bsuid(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    contact_id = await _resolve(bsuid="MA.hidden-number", wa_id=None, profile_name="Youssef")
    row = await su.fetchrow("select full_name, country from contacts where id = $1", contact_id)
    assert (row["full_name"], row["country"]) == ("Youssef", "MA")
    assert (
        await su.fetchval(
            "select count(*) from contact_identities where contact_id = $1", contact_id
        )
        == 1
    )


async def test_a_human_edited_name_is_not_replaced(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    contact_id = await _resolve(profile_name="WhatsApp Name")
    await su.execute(
        "update contacts set full_name = 'Human Name', profile_updated_at = now() where id = $1",
        contact_id,
    )
    await _resolve(profile_name="Changed WhatsApp Name")
    assert (
        await su.fetchval("select full_name from contacts where id = $1", contact_id)
        == "Human Name"
    )


async def test_ten_simultaneous_first_messages_create_one_customer(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    results = await asyncio.gather(
        *(
            _resolve(
                bsuid="AE.concurrent",
                wa_id="971500006666",
                profile_name=f"Concurrent {index}",
            )
            for index in range(10)
        )
    )
    assert len(set(results)) == 1
    assert (
        await su.fetchval(
            """select count(distinct contact_id) from contact_identities
               where tenant_id = $1 and value in ('AE.concurrent', '+971500006666')""",
            TENANT_A,
        )
        == 1
    )


async def test_at_least_one_identity_is_required(db: None, seeded: None) -> None:
    with pytest.raises(ValueError, match="identity"):
        await _resolve(bsuid=None, wa_id=None)


async def test_an_unreadable_wa_id_does_not_cost_us_the_message(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    """Meta may send something that is not a phone number, or nothing at all.

    Refusing the message would lose a customer's first contact over a field the
    BSUID already makes unnecessary.
    """
    contact_id = await _resolve(wa_id="AE.13491208655302741918")
    kinds = [
        row["kind"]
        for row in await su.fetch(
            "select kind from contact_identities where contact_id = $1", contact_id
        )
    ]
    assert kinds == ["whatsapp_user_id"], "a junk wa_id was stored as a phone number"


async def test_a_phone_only_customer_still_resolves(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    contact_id = await _resolve(bsuid=None)
    assert await su.fetchval(
        """select exists(select 1 from contact_identities
                         where contact_id = $1 and kind = 'phone' and value = '+971500009999')""",
        contact_id,
    )
