"""Opening a conversation, and the things a salesperson does to it."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator

import asyncpg
import pytest
from fastapi.testclient import TestClient

from conftest import (
    MANAGER,
    SALES_1,
    SALES_2,
    TEAM_LOCAL,
    TENANT_A,
    TENANT_B,
    USER_B,
    reseed_with_people,
)
from dealerai.config import get_settings
from dealerai.core.security import mint_test_token
from dealerai.main import app

SECRET = "super-secret-jwt-token-with-at-least-32-characters-long"
CHANNEL = uuid.UUID("cccccccc-7777-4777-8777-000000000001")
MINE = uuid.UUID("cccccccc-7777-4777-8777-000000000002")
UNASSIGNED = uuid.UUID("cccccccc-7777-4777-8777-000000000003")


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "supabase_jwt_secret", SECRET)


def _auth(user_id: uuid.UUID, tenant_id: uuid.UUID = TENANT_A) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {mint_test_token(user_id, secret=SECRET)}",
        "X-Tenant-Id": str(tenant_id),
    }


async def _seed_thread() -> None:
    await reseed_with_people()
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        await conn.execute(
            """insert into channels (id, tenant_id, platform, external_id, account_id, mode,
                                     display_name)
               values ($1, $2, 'whatsapp', 'thread-phone', 'thread-waba', 'coexistence',
                       'Pollux')""",
            CHANNEL,
            TENANT_A,
        )
        for conversation_id, assigned_to, name in (
            (MINE, SALES_1, "Karim Benali"),
            (UNASSIGNED, None, "Nadia Haddad"),
        ):
            contact_id = await conn.fetchval(
                """insert into contacts (tenant_id, full_name, owner_id, team_id)
                   values ($1, $2, $3, $4) returning id""",
                TENANT_A,
                name,
                assigned_to,
                TEAM_LOCAL,
            )
            await conn.execute(
                """insert into conversations
                     (id, tenant_id, contact_id, channel_id, surface, team_id, assigned_to,
                      owner_id, waiting_since, sla_due_at, last_message_at, wa_window_expires_at)
                   values ($1, $2, $3, $4, 'whatsapp', $5, $6, $6,
                           now() - interval '10 minutes', now() + interval '5 minutes',
                           now(), now() + interval '20 hours')""",
                conversation_id,
                TENANT_A,
                contact_id,
                CHANNEL,
                TEAM_LOCAL,
                assigned_to,
            )
        # A thread with one of everything the screen has to draw.
        await conn.execute(
            """insert into messages (tenant_id, conversation_id, direction, sender, origin, type,
                                     body, transcript, media, created_at)
               values ($1, $2, 'in', 'customer', 'customer', 'audio', null,
                       '{"text": "Is the white Land Cruiser available?", "language": "en"}'::jsonb,
                       '[{"external_id": "m1", "mime": "audio/ogg", "status": "ready",
                          "storage_path": "t/messages/2026/09/a.ogg", "size": 9620}]'::jsonb,
                       now() - interval '10 minutes')""",
            TENANT_A,
            MINE,
        )
        await conn.execute(
            """insert into messages (tenant_id, conversation_id, direction, sender, origin, type,
                                     body, author_user_id, status, created_at)
               values ($1, $2, 'out', 'human', 'inbox', 'text', 'Yes, it is.', $3, 'sent',
                       now() - interval '5 minutes')""",
            TENANT_A,
            MINE,
            SALES_1,
        )
        await conn.execute(
            """insert into messages (tenant_id, conversation_id, direction, sender, origin, type,
                                     body, status, error, created_at)
               values ($1, $2, 'out', 'human', 'inbox', 'text', 'Shall I hold it?', 'failed',
                       '{"code": "131047", "message": "Window closed"}'::jsonb,
                       now() - interval '4 minutes')""",
            TENANT_A,
            MINE,
        )
    finally:
        await conn.close()


@pytest.fixture
def client(_migrated: None) -> Iterator[TestClient]:
    asyncio.run(_seed_thread())
    with TestClient(app) as test_client:
        yield test_client


def _messages(client: TestClient, user: uuid.UUID = SALES_1) -> list[dict[str, object]]:
    response = client.get(f"/v1/conversations/{MINE}/messages", headers=_auth(user))
    assert response.status_code == 200, response.text
    return response.json()["data"]  # type: ignore[no-any-return]


def test_the_conversation_reads_like_its_row(client: TestClient) -> None:
    body = client.get(f"/v1/conversations/{MINE}", headers=_auth(SALES_1)).json()
    assert body["contact"]["name"] == "Karim Benali"
    assert body["assignee"]["id"] == str(SALES_1)
    assert body["sla_state"] in {"ok", "due_soon", "breached"}
    assert body["window_expires_at"]


def test_the_thread_comes_back_oldest_first_with_every_type(client: TestClient) -> None:
    messages = _messages(client)
    assert [(m["type"], m["origin"]) for m in messages] == [
        ("audio", "customer"),
        ("text", "inbox"),
        ("text", "inbox"),
    ]
    voice = messages[0]
    assert voice["transcript"]["text"].startswith("Is the white")  # type: ignore[index]
    assert voice["status"] is None, "ticks belong to messages we sent"
    assert messages[1]["author"]["name"] == "sales1"  # type: ignore[index]
    assert messages[2]["status"] == "failed"
    assert messages[2]["error"]["code"] == "131047"  # type: ignore[index]


def test_an_internal_note_is_never_sent(client: TestClient) -> None:
    created = client.post(
        f"/v1/conversations/{MINE}/notes",
        json={"text": "He bought from us in 2023."},
        headers=_auth(SALES_1),
    )
    assert created.status_code == 201, created.text
    note = created.json()
    assert note["kind"] == "note"
    assert note["status"] is None, "a note has no delivery state because it is never delivered"
    assert _messages(client)[-1]["kind"] == "note"
    assert asyncio.run(_events()) == [], "nothing was queued for WhatsApp"


async def _events() -> list[str]:
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        return [r["event_type"] for r in await conn.fetch("select event_type from events")]
    finally:
        await conn.close()


def test_opening_marks_it_read_for_me_only(client: TestClient) -> None:
    assert client.post(f"/v1/conversations/{MINE}/read", headers=_auth(SALES_1)).status_code == 204

    def unread(user: uuid.UUID, view: str) -> int:
        rows = client.get(f"/v1/conversations?view={view}", headers=_auth(user)).json()["data"]
        return next(row["unread_count"] for row in rows if row["id"] == str(MINE))  # type: ignore[no-any-return]

    assert unread(SALES_1, "mine") == 0
    assert unread(MANAGER, "team") == 1, "the manager has not read it"


def test_a_salesperson_can_claim_an_unassigned_conversation(client: TestClient) -> None:
    response = client.post(
        f"/v1/conversations/{UNASSIGNED}/assign",
        json={"user_id": str(SALES_1)},
        headers=_auth(SALES_1),
    )
    assert response.status_code == 200, response.text
    assert response.json()["assignee"]["id"] == str(SALES_1)


def test_a_salesperson_cannot_hand_it_to_someone_else(client: TestClient) -> None:
    """Claiming is not assigning: inbox.assign is a manager's permission."""
    response = client.post(
        f"/v1/conversations/{UNASSIGNED}/assign",
        json={"user_id": str(SALES_2)},
        headers=_auth(SALES_1),
    )
    assert response.status_code == 403


def test_a_manager_may_assign_anyone(client: TestClient) -> None:
    response = client.post(
        f"/v1/conversations/{UNASSIGNED}/assign",
        json={"user_id": str(SALES_2)},
        headers=_auth(MANAGER),
    )
    assert response.status_code == 200
    assert response.json()["assignee"]["id"] == str(SALES_2)
    [line] = [e for e in _thread_events(client, UNASSIGNED, MANAGER) if e["type"] == "assigned"]  # type: ignore[index]
    assert line["text"].startswith("Assigned to ")  # type: ignore[index]
    assert line["text"] == f"Assigned to {line['name']}"  # type: ignore[index]


def _thread_events(client: TestClient, conversation_id: uuid.UUID, user: uuid.UUID) -> list[object]:
    messages = client.get(
        f"/v1/conversations/{conversation_id}/messages", headers=_auth(user)
    ).json()["data"]
    return [m["event"] for m in messages if m["kind"] == "event"]


def test_closing_stops_the_timer_and_leaves_a_line(client: TestClient) -> None:
    response = client.post(
        f"/v1/conversations/{MINE}/status", json={"status": "closed"}, headers=_auth(SALES_1)
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "closed"
    assert body["waiting_since"] is None and body["sla_state"] is None
    assert _messages(client)[-1]["event"]["type"] == "closed"  # type: ignore[index]


def test_a_failed_message_can_be_sent_again_as_itself(client: TestClient) -> None:
    failed = next(m for m in _messages(client) if m["status"] == "failed")
    response = client.post(f"/v1/messages/{failed['id']}/retry", headers=_auth(SALES_1))
    assert response.status_code == 202, response.text
    assert response.json()["id"] == failed["id"], "a retry is the same message, not a second one"
    assert response.json()["status"] == "queued"
    assert "whatsapp.send_requested" in asyncio.run(_events())


def test_only_a_failed_message_can_be_retried(client: TestClient) -> None:
    """A message still sending is the ambiguous case the watchdog owns."""
    sent = next(m for m in _messages(client) if m["status"] == "sent")
    assert (
        client.post(f"/v1/messages/{sent['id']}/retry", headers=_auth(SALES_1)).status_code == 404
    )


def test_another_tenant_sees_none_of_it(client: TestClient) -> None:
    for path in ("", "/messages"):
        assert (
            client.get(
                f"/v1/conversations/{MINE}{path}", headers=_auth(USER_B, TENANT_B)
            ).status_code
            == 404
        )
    assert (
        client.post(f"/v1/conversations/{MINE}/read", headers=_auth(USER_B, TENANT_B)).status_code
        == 404
    )


def test_a_colleagues_conversation_is_not_there_either(client: TestClient) -> None:
    assert client.get(f"/v1/conversations/{MINE}", headers=_auth(SALES_2)).status_code == 404, (
        "404, not 403: the reply must not confirm the conversation exists"
    )
