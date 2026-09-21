"""Reassign and merge: five tables, one transaction, one invariant.

The invariant is `conversations.owner_id = contacts.owner_id`, which the inbox's
visibility policy is built on — a conversation owned by one person and answered
by another is the state the queue cannot explain.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import asyncpg
import pytest

from conftest import TENANT_A, TENANT_B, USER_A, USER_B
from dealerai.db.session import tenant_session


async def _board(conn: asyncpg.Connection, tenant_id: uuid.UUID, category: str) -> uuid.UUID:
    """A stage of the tenant's default board, by category."""
    stage = await conn.fetchval(
        """select s.id from pipeline_stages s join pipelines p on p.id = s.pipeline_id
            where s.tenant_id = $1 and s.category = $2
            order by p.is_default desc, s.position limit 1""",
        tenant_id,
        category,
    )
    assert stage is not None, "the seeded tenant has a board"
    return uuid.UUID(str(stage))


async def _customer(
    conn: asyncpg.Connection,
    *,
    owner: uuid.UUID | None,
    name: str = "Omar Al Mazrouei",
    tenant_id: uuid.UUID = TENANT_A,
    profile: dict[str, Any] | None = None,
    tags: list[str] | None = None,
) -> uuid.UUID:
    contact = await conn.fetchval(
        """insert into contacts (tenant_id, full_name, owner_id, profile, tags)
           values ($1, $2, $3, $4::jsonb, $5) returning id""",
        tenant_id,
        name,
        owner,
        json.dumps(profile or {}),
        tags or [],
    )
    return uuid.UUID(str(contact))


async def _identity(
    conn: asyncpg.Connection, contact: uuid.UUID, kind: str, value: str, tenant_id: uuid.UUID
) -> None:
    await conn.execute(
        """insert into contact_identities (tenant_id, contact_id, kind, value, is_primary)
           values ($1, $2, $3, $4, true)""",
        tenant_id,
        contact,
        kind,
        value,
    )


async def _a_customer_with_everything(
    conn: asyncpg.Connection, *, owner: uuid.UUID
) -> dict[str, uuid.UUID]:
    """One customer, one open conversation, an open lead, a won lead and a task."""
    contact = await _customer(conn, owner=owner)
    conversation = await conn.fetchval(
        """insert into conversations (tenant_id, contact_id, surface, status, owner_id, assigned_to)
           values ($1, $2, 'whatsapp', 'open', $3, $3) returning id""",
        TENANT_A,
        contact,
        owner,
    )
    await conn.execute(
        """insert into messages (tenant_id, conversation_id, direction, sender, origin, body)
           values ($1, $2, 'in', 'customer', 'customer', 'Is it still available?')""",
        TENANT_A,
        conversation,
    )
    pipeline = await conn.fetchval(
        "select pipeline_id from pipeline_stages where id = $1",
        await _board(conn, TENANT_A, "open"),
    )
    open_lead = await conn.fetchval(
        """insert into leads (tenant_id, contact_id, pipeline_id, stage_id, owner_id)
           values ($1, $2, $3, $4, $5) returning id""",
        TENANT_A,
        contact,
        pipeline,
        await _board(conn, TENANT_A, "open"),
        owner,
    )
    won_lead = await conn.fetchval(
        """insert into leads (tenant_id, contact_id, pipeline_id, stage_id, owner_id)
           values ($1, $2, $3, $4, $5) returning id""",
        TENANT_A,
        contact,
        pipeline,
        await _board(conn, TENANT_A, "won"),
        owner,
    )
    task = await conn.fetchval(
        """insert into tasks (tenant_id, title, due_at, assignee_id, contact_id)
           values ($1, 'Call about the Hilux', now(), $2, $3) returning id""",
        TENANT_A,
        owner,
        contact,
    )
    return {
        "contact": contact,
        "conversation": conversation,
        "open_lead": open_lead,
        "won_lead": won_lead,
        "task": task,
    }


async def _reassign(contact: uuid.UUID, new_owner: uuid.UUID, actor: uuid.UUID) -> None:
    async with tenant_session(TENANT_A) as conn:
        await conn.execute("select app.reassign_contact($1, $2, $3)", contact, new_owner, actor)


async def _merge(keep: uuid.UUID, merge: uuid.UUID, actor: uuid.UUID) -> None:
    async with tenant_session(TENANT_A) as conn:
        await conn.execute("select app.merge_contacts($1, $2, $3)", keep, merge, actor)


async def test_reassigning_moves_the_work_and_says_so_in_the_thread(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    rows = await _a_customer_with_everything(su, owner=USER_A)

    await _reassign(rows["contact"], USER_B, USER_A)

    assert (
        await su.fetchval("select owner_id from contacts where id = $1", rows["contact"]) == USER_B
    )
    conversation = await su.fetchrow(
        "select owner_id, assigned_to from conversations where id = $1", rows["conversation"]
    )
    assert (conversation["owner_id"], conversation["assigned_to"]) == (USER_B, USER_B)
    assert (
        await su.fetchval("select owner_id from leads where id = $1", rows["open_lead"]) == USER_B
    )
    assert await su.fetchval("select assignee_id from tasks where id = $1", rows["task"]) == USER_B

    event = await su.fetchval(
        """select event from messages where conversation_id = $1 and kind = 'event'
            order by created_at desc limit 1""",
        rows["conversation"],
    )
    line = json.loads(event)
    assert line["type"] == "reassigned"
    assert line["to"] == str(USER_B)
    assert line["text"], "a grey line with no words is a grey line nobody can read"


async def test_a_closed_lead_stays_with_whoever_closed_it(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    """Moving a won lead would rewrite somebody's month."""
    rows = await _a_customer_with_everything(su, owner=USER_A)

    await _reassign(rows["contact"], USER_B, USER_A)

    assert await su.fetchval("select owner_id from leads where id = $1", rows["won_lead"]) == USER_A


async def test_a_completed_task_stays_with_whoever_did_it(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    rows = await _a_customer_with_everything(su, owner=USER_A)
    done = await su.fetchval(
        """insert into tasks (tenant_id, title, due_at, assignee_id, contact_id, status,
                              completed_at)
           values ($1, 'Called yesterday', now(), $2, $3, 'done', now()) returning id""",
        TENANT_A,
        USER_A,
        rows["contact"],
    )

    await _reassign(rows["contact"], USER_B, USER_A)

    assert await su.fetchval("select assignee_id from tasks where id = $1", done) == USER_A


async def test_merging_moves_everything_and_leaves_one_customer(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    kept = await _a_customer_with_everything(su, owner=USER_A)
    duplicate = await _a_customer_with_everything(su, owner=USER_B)
    await _identity(su, duplicate["contact"], "phone", "+971500000999", TENANT_A)

    await _merge(kept["contact"], duplicate["contact"], USER_A)

    assert (
        await su.fetchval("select count(*) from contacts where id = $1", duplicate["contact"]) == 0
    )
    for table, column, row_id in (
        ("conversations", "contact_id", duplicate["conversation"]),
        ("leads", "contact_id", duplicate["open_lead"]),
        ("tasks", "contact_id", duplicate["task"]),
    ):
        moved = await su.fetchval(f"select {column} from {table} where id = $1", row_id)  # noqa: S608
        assert moved == kept["contact"], f"{table} was left pointing at a deleted customer"
    assert (
        await su.fetchval(
            "select contact_id from contact_identities where value = $1", "+971500000999"
        )
        == kept["contact"]
    )


async def test_the_kept_customer_wins_where_it_knows_anything(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    """docs/sales/05-workflows.md § 10: keep's human values, then keep's AI
    ones, then whatever only the duplicate knew."""
    kept = await _customer(
        su,
        owner=USER_A,
        profile={
            "timeline": {"value": "This week", "source": "human"},
            "budget": {"value": {"amount_minor": 15_000_000}, "source": "ai"},
        },
    )
    duplicate = await _customer(
        su,
        owner=USER_A,
        name="Omar (duplicate)",
        profile={
            "timeline": {"value": "Next month", "source": "ai"},
            "budget": {"value": {"amount_minor": 12_000_000}, "source": "human"},
            "payment": {"value": "finance", "source": "ai"},
        },
    )

    await _merge(kept, duplicate, USER_A)

    profile = json.loads(await su.fetchval("select profile from contacts where id = $1", kept))
    assert profile["timeline"]["value"] == "This week", "a person's answer was overwritten"
    # The spec's order, and its cost: a guess on the kept record beats a
    # person's answer on the duplicate. The dialog shows both before confirming.
    assert profile["budget"]["value"]["amount_minor"] == 15_000_000
    assert profile["payment"]["value"] == "finance", "what only the duplicate knew was lost"


async def test_the_moved_identities_do_not_fight_over_being_primary(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    """Two customers in one workspace cannot hold the same number — unique
    (tenant_id, kind, value) sees to that — so a merge moves identities
    wholesale. What it must not do is arrive with a second primary phone."""
    kept = await _customer(su, owner=USER_A)
    duplicate = await _customer(su, owner=USER_A, name="Omar (duplicate)")
    await _identity(su, kept, "phone", "+971500000101", TENANT_A)
    await _identity(su, duplicate, "phone", "+971500000102", TENANT_A)

    await _merge(kept, duplicate, USER_A)

    numbers = await su.fetch(
        "select value, is_primary from contact_identities where contact_id = $1 order by value",
        kept,
    )
    assert [(row["value"], row["is_primary"]) for row in numbers] == [
        ("+971500000101", True),
        ("+971500000102", False),
    ]


async def test_customers_in_two_workspaces_cannot_be_merged(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    kept = await _customer(su, owner=USER_A)
    theirs = await _customer(su, owner=USER_B, name="Their customer", tenant_id=TENANT_B)

    with pytest.raises(asyncpg.PostgresError, match="different workspaces"):
        await _merge(kept, theirs, USER_A)

    assert await su.fetchval("select count(*) from contacts where id = $1", theirs) == 1


async def test_a_customer_cannot_be_merged_into_itself(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    kept = await _customer(su, owner=USER_A)
    with pytest.raises(asyncpg.PostgresError, match="into itself"):
        await _merge(kept, kept, USER_A)


async def test_both_writes_leave_an_audit_trail(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    """A merge is not undoable; the snapshot is what a repair would start from."""
    kept = await _a_customer_with_everything(su, owner=USER_A)
    duplicate = await _customer(su, owner=USER_B, name="Omar (duplicate)")

    await _reassign(kept["contact"], USER_B, USER_A)
    await _merge(kept["contact"], duplicate, USER_A)

    reassigned = await su.fetchrow(
        "select before, after from audit_log where action = 'contact.reassigned'"
    )
    assert json.loads(reassigned["before"])["owner_id"] == str(USER_A)
    assert json.loads(reassigned["after"])["owner_id"] == str(USER_B)

    merged = await su.fetchrow(
        "select entity_id, before, meta from audit_log where action = 'contact.merged'"
    )
    assert merged["entity_id"] == duplicate
    assert json.loads(merged["before"])["full_name"] == "Omar (duplicate)"
    assert json.loads(merged["meta"])["keep_id"] == str(kept["contact"])


async def test_the_owner_of_a_conversation_is_always_the_owner_of_its_customer(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    """The invariant the inbox's visibility policy is built on, after both writes."""
    kept = await _a_customer_with_everything(su, owner=USER_A)
    duplicate = await _a_customer_with_everything(su, owner=USER_B)

    await _reassign(kept["contact"], USER_B, USER_A)
    await _merge(kept["contact"], duplicate["contact"], USER_A)

    mismatched = await su.fetchval(
        """select count(*) from conversations c join contacts k on k.id = c.contact_id
            where c.status = 'open' and c.owner_id is distinct from k.owner_id"""
    )
    assert mismatched == 0
