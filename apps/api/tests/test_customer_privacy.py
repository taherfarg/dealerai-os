"""A customer's copy of their data, and their erasure — UAE PDPL."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient

from conftest import (
    MANAGER,
    OWNER,
    SALES_1,
    TEAM_LOCAL,
    TENANT_A,
    TENANT_B,
    reseed_with_people,
)
from dealerai.config import get_settings
from dealerai.core.security import mint_test_token
from dealerai.events.bus import Event
from dealerai.events.handlers.privacy import on_media_delete
from dealerai.main import app

SECRET = "super-secret-jwt-token-with-at-least-32-characters-long"
PASSPORT = f"{TENANT_A}/messages/2026/09/passport.jpg"


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "supabase_jwt_secret", SECRET)


def _auth(user_id: uuid.UUID) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {mint_test_token(user_id, secret=SECRET)}",
        "X-Tenant-Id": str(TENANT_A),
    }


async def _everywhere() -> dict[str, uuid.UUID]:
    """Omar in every table that can hold him; Mona beside him."""
    await reseed_with_people()
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        omar = await conn.fetchval(
            """insert into contacts (tenant_id, full_name, owner_id, team_id)
               values ($1, 'Omar Haddad', $2, $3) returning id""",
            TENANT_A,
            SALES_1,
            TEAM_LOCAL,
        )
        await conn.execute(
            """insert into contact_identities (tenant_id, contact_id, kind, value, is_primary)
               values ($1, $2, 'phone', '+971500000001', true)""",
            TENANT_A,
            omar,
        )
        conversation = await conn.fetchval(
            """insert into conversations (tenant_id, contact_id, surface, owner_id, team_id,
                                          assigned_to)
               values ($1, $2, 'whatsapp', $3, $4, $3) returning id""",
            TENANT_A,
            omar,
            SALES_1,
            TEAM_LOCAL,
        )
        message = await conn.fetchval(
            """insert into messages (tenant_id, conversation_id, direction, sender, origin,
                                     body, media)
               values ($1, $2, 'in', 'customer', 'customer', 'my passport', $3::jsonb)
               returning id""",
            TENANT_A,
            conversation,
            json.dumps([{"status": "ready", "storage_path": PASSPORT, "mime": "image/jpeg"}]),
        )
        await conn.execute(
            """insert into ai_suggestions (tenant_id, conversation_id, for_message_id, status,
                                           text)
               values ($1, $2, $3, 'ready', 'Thank you Omar')""",
            TENANT_A,
            conversation,
            message,
        )
        await conn.execute(
            """insert into sla_misses (tenant_id, conversation_id, assigned_to, waiting_since,
                                       due_at)
               values ($1, $2, $3, now() - interval '9 minutes', now() - interval '4 minutes')""",
            TENANT_A,
            conversation,
            SALES_1,
        )
        await conn.execute(
            """insert into conversation_reads (tenant_id, conversation_id, user_id, last_read_at)
               values ($1, $2, $3, now())""",
            TENANT_A,
            conversation,
            SALES_1,
        )
        stage = await conn.fetchrow(
            """select pipeline_id, id from pipeline_stages
                where tenant_id = $1 and category = 'open' order by position limit 1""",
            TENANT_A,
        )
        lead = await conn.fetchval(
            """insert into leads (tenant_id, contact_id, conversation_id, pipeline_id, stage_id,
                                  owner_id, team_id)
               values ($1, $2, $3, $4, $5, $6, $7) returning id""",
            TENANT_A,
            omar,
            conversation,
            stage["pipeline_id"],
            stage["id"],
            SALES_1,
            TEAM_LOCAL,
        )
        task = await conn.fetchval(
            """insert into tasks (tenant_id, title, due_at, assignee_id, lead_id)
               values ($1, 'Call Omar about the Patrol', now(), $2, $3) returning id""",
            TENANT_A,
            SALES_1,
            lead,
        )
        # Somebody else's notification about him: only a session without a user reaches it.
        await conn.execute(
            """insert into notifications (tenant_id, user_id, kind, title, entity)
               values ($1, $2, 'lead_hot', 'Omar Haddad is now a hot lead', $3::jsonb)""",
            TENANT_A,
            MANAGER,
            json.dumps({"type": "lead", "id": str(lead)}),
        )
        run = await conn.fetchval(
            """insert into agent_runs (tenant_id, trigger_type, autonomy, goal, goal_input)
               values ($1, 'event', 'copilot', 'draft', $2::jsonb) returning id""",
            TENANT_A,
            json.dumps({"conversation_id": str(conversation)}),
        )
        await conn.execute(
            """insert into agent_traces (tenant_id, run_id, kind, name, status, payload)
               values ($1, $2, 'tool', 'search_knowledge', 'ok', $3::jsonb)""",
            TENANT_A,
            run,
            json.dumps({"arguments": {"query": "Omar's passport"}}),
        )
        await conn.execute(
            """insert into events (tenant_id, event_type, payload, run_after)
               values ($1, 'conversation.idle', $2::jsonb, now() + interval '1 hour')""",
            TENANT_A,
            json.dumps({"conversation_id": str(conversation)}),
        )
        # The snapshot a merge left: both records, whole.
        await conn.execute(
            """insert into audit_log (tenant_id, actor_type, actor_id, action, entity_type,
                                      entity_id, before, after, meta)
               values ($1, 'user', $2, 'contact.merged', 'contact', gen_random_uuid(),
                       '{"full_name": "Omar H"}', '{"full_name": "Omar Haddad"}', $3::jsonb)""",
            TENANT_A,
            str(OWNER),
            json.dumps({"keep_id": str(omar)}),
        )
        mona = await conn.fetchval(
            """insert into contacts (tenant_id, full_name, owner_id, team_id)
               values ($1, 'Mona Fathy', $2, $3) returning id""",
            TENANT_A,
            SALES_1,
            TEAM_LOCAL,
        )
        return {
            "omar": omar,
            "conversation": conversation,
            "lead": lead,
            "task": task,
            "run": run,
            "mona": mona,
        }
    finally:
        await conn.close()


async def _rows(sql: str, *args: object) -> list[asyncpg.Record]:
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        return list(await conn.fetch(sql, *args))
    finally:
        await conn.close()


def _count(sql: str, *args: object) -> int:
    return int(asyncio.run(_rows(sql, *args))[0][0])


@pytest.fixture
def ids(_migrated: None) -> dict[str, uuid.UUID]:
    return asyncio.run(_everywhere())


@pytest.fixture
def client(ids: dict[str, uuid.UUID]) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def _erase(client: TestClient, customer_id: uuid.UUID, user: uuid.UUID = OWNER) -> Any:
    return client.delete(f"/v1/customers/{customer_id}", headers=_auth(user))


def _export(client: TestClient, customer_id: uuid.UUID, user: uuid.UUID = OWNER) -> Any:
    return client.get(f"/v1/customers/{customer_id}/export", headers=_auth(user))


# ---------------------------------------------------------------------------
# erasure
# ---------------------------------------------------------------------------


def test_erasure_leaves_nothing_of_them(client: TestClient, ids: dict[str, uuid.UUID]) -> None:
    response = _erase(client, ids["omar"])
    assert response.status_code == 204, response.text
    for sql, value in (
        ("select count(*) from contacts where id = $1", ids["omar"]),
        ("select count(*) from contact_identities where contact_id = $1", ids["omar"]),
        ("select count(*) from conversations where id = $1", ids["conversation"]),
        ("select count(*) from messages where conversation_id = $1", ids["conversation"]),
        ("select count(*) from ai_suggestions where conversation_id = $1", ids["conversation"]),
        ("select count(*) from sla_misses where conversation_id = $1", ids["conversation"]),
        (
            "select count(*) from conversation_reads where conversation_id = $1",
            ids["conversation"],
        ),
        ("select count(*) from leads where id = $1", ids["lead"]),
        ("select count(*) from tasks where id = $1", ids["task"]),
        ("select count(*) from notifications where entity->>'id' = $1", str(ids["lead"])),
        ("select count(*) from agent_runs where id = $1", ids["run"]),
        ("select count(*) from agent_traces where run_id = $1", ids["run"]),
        (
            "select count(*) from events where event_type = 'conversation.idle'"
            " and payload->>'conversation_id' = $1",
            str(ids["conversation"]),
        ),
        (
            "select count(*) from audit_log where action = 'contact.merged'"
            " and before is not null and meta->>'keep_id' = $1",
            str(ids["omar"]),
        ),
    ):
        assert _count(sql, value) == 0, sql


def test_the_audit_says_who_and_when_and_never_what(
    client: TestClient, ids: dict[str, uuid.UUID]
) -> None:
    _erase(client, ids["omar"])
    [erased] = asyncio.run(
        _rows(
            """select actor_type, actor_id, meta, before, after from audit_log
                where action = 'contact.erased' and entity_id = $1""",
            ids["omar"],
        )
    )
    assert (erased["actor_type"], erased["actor_id"]) == ("user", str(OWNER))
    assert json.loads(erased["meta"]) == {"reason": "request"}
    assert (erased["before"], erased["after"]) == (None, None)
    [merged] = asyncio.run(
        _rows("select before, after, meta from audit_log where action = 'contact.merged'")
    )
    assert (merged["before"], merged["after"]) == (None, None)
    assert json.loads(merged["meta"]) == {"keep_id": str(ids["omar"])}


def test_their_files_are_queued_for_deletion(client: TestClient, ids: dict[str, uuid.UUID]) -> None:
    _erase(client, ids["omar"])
    rows = asyncio.run(
        _rows(
            """select payload from events
                where tenant_id = $1 and event_type = 'media.delete' and status = 'pending'""",
            TENANT_A,
        )
    )
    assert [json.loads(row["payload"])["paths"] for row in rows] == [[PASSPORT]]


def test_the_customer_beside_them_is_untouched(
    client: TestClient, ids: dict[str, uuid.UUID]
) -> None:
    _erase(client, ids["omar"])
    assert _count("select count(*) from contacts where id = $1", ids["mona"]) == 1


@pytest.mark.parametrize("user", [MANAGER, SALES_1])
def test_only_an_owner_or_an_admin_may_erase(
    client: TestClient, ids: dict[str, uuid.UUID], user: uuid.UUID
) -> None:
    assert _erase(client, ids["omar"], user).status_code == 403
    assert _count("select count(*) from contacts where id = $1", ids["omar"]) == 1


def test_erasing_somebody_you_cannot_see_is_a_404(
    client: TestClient, ids: dict[str, uuid.UUID]
) -> None:
    [beta] = asyncio.run(_rows("select id from contacts where tenant_id = $1", TENANT_B))
    assert _erase(client, beta["id"]).status_code == 404
    assert _count("select count(*) from contacts where id = $1", beta["id"]) == 1


def test_erasing_twice_is_a_404_the_second_time(
    client: TestClient, ids: dict[str, uuid.UUID]
) -> None:
    assert _erase(client, ids["omar"]).status_code == 204
    assert _erase(client, ids["omar"]).status_code == 404


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------


def test_an_export_holds_everything_the_erasure_would_remove(
    client: TestClient, ids: dict[str, uuid.UUID]
) -> None:
    response = _export(client, ids["omar"])
    assert response.status_code == 200, response.text
    assert response.headers["content-disposition"] == (
        f'attachment; filename="customer-{ids["omar"]}.json"'
    )
    document = response.json()
    assert document["customer"]["name"] == "Omar Haddad"
    assert document["identities"] == [{"kind": "phone", "value": "+971500000001"}]
    [message] = document["messages"]
    assert message["body"] == "my passport"
    [media] = message["media"]
    # Absolute: the file is read outside the app, by the customer.
    assert media["url"].startswith("http") and "/v1/media/" in media["url"]
    assert [lead["id"] for lead in document["leads"]] == [str(ids["lead"])]
    assert [task["title"] for task in document["tasks"]] == ["Call Omar about the Patrol"]


def test_an_export_is_itself_audited(client: TestClient, ids: dict[str, uuid.UUID]) -> None:
    _export(client, ids["omar"])
    rows = asyncio.run(
        _rows(
            """select actor_id, before, after from audit_log
                where action = 'contact.exported' and entity_id = $1""",
            ids["omar"],
        )
    )
    assert [(row["actor_id"], row["before"], row["after"]) for row in rows] == [
        (str(OWNER), None, None)
    ]


@pytest.mark.parametrize("user", [MANAGER, SALES_1])
def test_only_owners_and_admins_export(
    client: TestClient, ids: dict[str, uuid.UUID], user: uuid.UUID
) -> None:
    assert _export(client, ids["omar"], user).status_code == 403


# ---------------------------------------------------------------------------
# the worker's half
# ---------------------------------------------------------------------------


async def test_media_delete_removes_the_files_and_forgives_the_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "storage_dir", str(tmp_path))
    kept = tmp_path / PASSPORT
    kept.parent.mkdir(parents=True)
    kept.write_bytes(b"jpeg")
    event = Event(
        1, TENANT_A, "media.delete", {"paths": [PASSPORT, f"{TENANT_A}/messages/gone.jpg"]}, 1, None
    )
    await on_media_delete(event)  # a retry after a partial run must not fail either
    assert not kept.exists()


async def test_media_delete_refuses_another_tenants_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "storage_dir", str(tmp_path))
    path = f"{TENANT_B}/messages/2026/09/theirs.jpg"
    theirs = tmp_path / path
    theirs.parent.mkdir(parents=True)
    theirs.write_bytes(b"jpeg")
    await on_media_delete(Event(1, TENANT_A, "media.delete", {"paths": [path]}, 1, None))
    assert theirs.exists()
