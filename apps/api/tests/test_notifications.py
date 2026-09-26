"""Notifications reach one person, once, and only they can read them."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator

import asyncpg
import pytest
from fastapi.testclient import TestClient

from conftest import MANAGER, OWNER, SALES_1, TEAM_LOCAL, TENANT_A, reseed_with_people
from dealerai.config import get_settings
from dealerai.core.security import mint_test_token
from dealerai.events.bus import Event
from dealerai.events.handlers import inbox
from dealerai.main import app

SECRET = "super-secret-jwt-token-with-at-least-32-characters-long"
CHANNEL = uuid.UUID("cccccccc-4444-4444-8444-000000000001")


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "supabase_jwt_secret", SECRET)


def _auth(user_id: uuid.UUID, tenant_id: uuid.UUID = TENANT_A) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {mint_test_token(user_id, secret=SECRET)}",
        "X-Tenant-Id": str(tenant_id),
    }


def _event(payload: dict[str, object]) -> Event:
    return Event(
        id=1,
        tenant_id=TENANT_A,
        event_type="notification.requested",
        payload=payload,
        attempts=1,
        dedupe_key=None,
    )


async def _channel(su: asyncpg.Connection) -> uuid.UUID:
    await su.execute(
        """insert into channels (id, tenant_id, platform, external_id, account_id, mode)
           values ($1, $2, 'whatsapp', 'notify-phone', 'notify-waba', 'cloud_api')
           on conflict (platform, external_id) do nothing""",
        CHANNEL,
        TENANT_A,
    )
    return CHANNEL


async def _conversation(
    su: asyncpg.Connection, *, assigned_to: uuid.UUID | None, team_id: uuid.UUID | None = TEAM_LOCAL
) -> uuid.UUID:
    await _channel(su)
    contact_id = await su.fetchval(
        "insert into contacts (tenant_id, full_name) values ($1, 'Karim Benali') returning id",
        TENANT_A,
    )
    return await su.fetchval(  # type: ignore[no-any-return]
        """insert into conversations
             (tenant_id, contact_id, channel_id, surface, team_id, assigned_to, owner_id)
           values ($1, $2, $3, 'whatsapp', $4, $5, $5) returning id""",
        TENANT_A,
        contact_id,
        CHANNEL,
        team_id,
        assigned_to,
    )


async def _message(su: asyncpg.Connection, conversation_id: uuid.UUID) -> uuid.UUID:
    return await su.fetchval(  # type: ignore[no-any-return]
        """insert into messages (tenant_id, conversation_id, direction, sender, origin, body)
           values ($1, $2, 'in', 'customer', 'customer', 'Is it available?') returning id""",
        TENANT_A,
        conversation_id,
    )


@pytest.fixture
async def workspace(su: asyncpg.Connection) -> asyncpg.Connection:
    await reseed_with_people()
    return su


async def test_the_assignee_hears_about_their_customer(
    db: None, workspace: asyncpg.Connection
) -> None:
    su = workspace
    conversation_id = await _conversation(su, assigned_to=SALES_1)
    message_id = await _message(su, conversation_id)

    await inbox.on_notification_requested(
        _event({"conversation_id": str(conversation_id), "message_id": str(message_id)})
    )

    rows = await su.fetch("select user_id, kind, title, href from notifications")
    assert [(r["user_id"], r["kind"]) for r in rows] == [(SALES_1, "message_received")]
    assert rows[0]["href"] == f"/inbox/{conversation_id}"
    assert "Karim Benali" in rows[0]["title"]


async def test_an_unassigned_customer_is_the_managers_problem(
    db: None, workspace: asyncpg.Connection
) -> None:
    su = workspace
    conversation_id = await _conversation(su, assigned_to=None)
    message_id = await _message(su, conversation_id)

    await inbox.on_notification_requested(
        _event({"conversation_id": str(conversation_id), "message_id": str(message_id)})
    )

    assert [r["user_id"] for r in await su.fetch("select user_id from notifications")] == [MANAGER]


async def test_the_same_message_notifies_once(db: None, workspace: asyncpg.Connection) -> None:
    su = workspace
    conversation_id = await _conversation(su, assigned_to=SALES_1)
    message_id = await _message(su, conversation_id)
    event = _event({"conversation_id": str(conversation_id), "message_id": str(message_id)})

    await inbox.on_notification_requested(event)
    await inbox.on_notification_requested(event)

    assert await su.fetchval("select count(*) from notifications") == 1


async def test_a_rejected_template_reaches_the_people_who_can_fix_it(
    db: None, workspace: asyncpg.Connection
) -> None:
    su = workspace
    channel_id = await _channel(su)

    await inbox.on_notification_requested(
        _event(
            {
                "kind": "template_rejected",
                "channel_id": str(channel_id),
                "template_id": str(uuid.uuid4()),
            }
        )
    )

    roles = await su.fetch(
        """select m.role from notifications n
           join memberships m on m.user_id = n.user_id and m.tenant_id = n.tenant_id"""
    )
    assert {r["role"] for r in roles} == {"owner"}, "only owners and admins can act on this"


async def test_a_kind_nobody_declared_is_ignored(db: None, workspace: asyncpg.Connection) -> None:
    await inbox.on_notification_requested(_event({"kind": "invented_later"}))
    assert await workspace.fetchval("select count(*) from notifications") == 0


# --------------------------------------------------------------------------
# reading them
# --------------------------------------------------------------------------


@pytest.fixture
def client(_migrated: None) -> Iterator[TestClient]:
    asyncio.run(_seed_notifications())
    with TestClient(app) as test_client:
        yield test_client


async def _seed_notifications() -> None:
    await reseed_with_people()
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        for title in ("A customer is waiting for you", "Karim Benali sent a message"):
            await conn.execute(
                """insert into notifications (tenant_id, user_id, kind, title)
                   values ($1, $2, 'assigned', $3)""",
                TENANT_A,
                SALES_1,
                title,
            )
    finally:
        await conn.close()


def test_a_person_reads_only_their_own(client: TestClient) -> None:
    mine = client.get("/v1/notifications", headers=_auth(SALES_1))
    assert mine.status_code == 200
    body = mine.json()
    assert len(body["data"]) == 2 and body["unread"] == 2
    assert client.get("/v1/notifications", headers=_auth(OWNER)).json()["data"] == []


def test_marking_read_is_idempotent(client: TestClient) -> None:
    ids = [n["id"] for n in client.get("/v1/notifications", headers=_auth(SALES_1)).json()["data"]]
    for _ in range(2):
        assert (
            client.post(
                "/v1/notifications/read", json={"ids": ids}, headers=_auth(SALES_1)
            ).status_code
            == 204
        )
    body = client.get("/v1/notifications?unread_only=true", headers=_auth(SALES_1)).json()
    assert body["data"] == [] and body["unread"] == 0


def test_marking_everything_read_needs_no_ids(client: TestClient) -> None:
    assert (
        client.post(
            "/v1/notifications/read", json={"all": True}, headers=_auth(SALES_1)
        ).status_code
        == 204
    )
    assert client.get("/v1/notifications", headers=_auth(SALES_1)).json()["unread"] == 0


def test_asking_for_both_or_neither_is_a_bad_request(client: TestClient) -> None:
    for body in ({}, {"ids": [str(uuid.uuid4())], "all": True}):
        assert (
            client.post("/v1/notifications/read", json=body, headers=_auth(SALES_1)).status_code
            == 400
        )
