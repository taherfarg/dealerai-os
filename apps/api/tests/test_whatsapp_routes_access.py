"""Who may use the WhatsApp routes, and whose conversations they can see.

Every new endpoint needs both (docs/sales/09-implementation-plan.md, definition
of done): a role that lacks the permission gets 403, and a row the caller cannot
see is 404 — the same answer another tenant's row gets, so neither is an oracle.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator

import asyncpg
import pytest
from fastapi.testclient import TestClient

from conftest import (
    MANAGER,
    OWNER,
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
CHANNEL_A = uuid.UUID("cccccccc-2222-4222-8222-000000000001")
CHANNEL_B = uuid.UUID("cccccccc-2222-4222-8222-000000000002")
VIEWER = uuid.UUID("cccccccc-1111-4000-8000-000000000009")


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "supabase_jwt_secret", SECRET)


async def _prepare() -> uuid.UUID:
    """Two tenants with a channel each, and one conversation owned by SALES_1."""
    await reseed_with_people()
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        # conftest's wipe only knows its own people; this one is ours to clear.
        await conn.execute("delete from auth.users where id = $1", VIEWER)
        await conn.execute(
            "insert into auth.users (id, email) values ($1, 'viewer@example.test')", VIEWER
        )
        await conn.execute(
            "insert into profiles (id, full_name, email) values ($1, 'viewer', $2)",
            VIEWER,
            "viewer@example.test",
        )
        await conn.execute(
            "insert into memberships (tenant_id, user_id, role) values ($1, $2, 'viewer')",
            TENANT_A,
            VIEWER,
        )
        for channel_id, tenant_id, phone in (
            (CHANNEL_A, TENANT_A, "phone-a"),
            (CHANNEL_B, TENANT_B, "phone-b"),
        ):
            await conn.execute(
                """insert into channels
                     (id, tenant_id, platform, external_id, account_id, mode, display_name)
                   values ($1, $2, 'whatsapp', $3, $3, 'cloud_api', 'WhatsApp')""",
                channel_id,
                tenant_id,
                phone,
            )
        contact_id = await conn.fetchval(
            """insert into contacts (tenant_id, full_name, owner_id, team_id)
               values ($1, 'Karim', $2, $3) returning id""",
            TENANT_A,
            SALES_1,
            TEAM_LOCAL,
        )
        await conn.execute(
            """insert into contact_identities (tenant_id, contact_id, kind, value, is_primary)
               values ($1, $2, 'whatsapp_user_id', 'AE.access.1', true)""",
            TENANT_A,
            contact_id,
        )
        return await conn.fetchval(  # type: ignore[no-any-return]
            """insert into conversations
                 (tenant_id, contact_id, channel_id, surface, owner_id, team_id, assigned_to,
                  wa_window_expires_at)
               values ($1, $2, $3, 'whatsapp', $4, $5, $4, now() + interval '2 hours')
               returning id""",
            TENANT_A,
            contact_id,
            CHANNEL_A,
            SALES_1,
            TEAM_LOCAL,
        )
    finally:
        await conn.close()


@pytest.fixture
def conversation_id(_migrated: None) -> uuid.UUID:
    return asyncio.run(_prepare())


@pytest.fixture
def client(conversation_id: uuid.UUID) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def auth(user_id: uuid.UUID, tenant_id: uuid.UUID = TENANT_A) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {mint_test_token(user_id, secret=SECRET)}",
        "X-Tenant-Id": str(tenant_id),
    }


def _send(client: TestClient, conversation_id: uuid.UUID, user: uuid.UUID, key: str):  # type: ignore[no-untyped-def]
    return client.post(
        f"/v1/conversations/{conversation_id}/messages",
        json={"text": "Yes, it is available."},
        headers={**auth(user), "Idempotency-Key": key},
    )


# --------------------------------------------------------------------------
# sending
# --------------------------------------------------------------------------


def test_the_owner_of_the_conversation_may_send(
    client: TestClient, conversation_id: uuid.UUID
) -> None:
    response = _send(client, conversation_id, SALES_1, "access-1")
    assert response.status_code == 202, response.text
    assert response.json()["status"] == "queued"


def test_a_viewer_may_not_send(client: TestClient, conversation_id: uuid.UUID) -> None:
    response = _send(client, conversation_id, VIEWER, "access-2")
    assert response.status_code == 403
    assert response.json()["type"].endswith("/forbidden")


def test_a_salesperson_cannot_send_into_a_colleagues_conversation(
    client: TestClient, conversation_id: uuid.UUID
) -> None:
    """404, not 403: the reply must not confirm that the conversation exists."""
    response = _send(client, conversation_id, SALES_2, "access-3")
    assert response.status_code == 404


def test_a_manager_sees_the_teams_conversation(
    client: TestClient, conversation_id: uuid.UUID
) -> None:
    assert _send(client, conversation_id, MANAGER, "access-4").status_code == 202


def test_another_tenant_gets_the_same_404(client: TestClient, conversation_id: uuid.UUID) -> None:
    response = client.post(
        f"/v1/conversations/{conversation_id}/messages",
        json={"text": "Hello"},
        headers={**auth(USER_B, TENANT_B), "Idempotency-Key": "access-5"},
    )
    assert response.status_code == 404


def test_sending_without_an_idempotency_key_is_refused(
    client: TestClient, conversation_id: uuid.UUID
) -> None:
    response = client.post(
        f"/v1/conversations/{conversation_id}/messages",
        json={"text": "Hello"},
        headers=auth(SALES_1),
    )
    assert response.status_code == 400


# --------------------------------------------------------------------------
# channels and templates
# --------------------------------------------------------------------------


def test_channels_are_listed_per_tenant(client: TestClient) -> None:
    mine = client.get("/v1/channels", headers=auth(SALES_1)).json()
    assert [channel["id"] for channel in mine] == [str(CHANNEL_A)]
    theirs = client.get("/v1/channels", headers=auth(USER_B, TENANT_B)).json()
    assert [channel["id"] for channel in theirs] == [str(CHANNEL_B)]


def test_another_tenants_channel_has_no_templates_to_show(client: TestClient) -> None:
    response = client.get(f"/v1/channels/{CHANNEL_B}/templates", headers=auth(OWNER))
    assert response.status_code == 404, "an empty list would confirm the channel exists"


def test_only_a_channel_admin_may_sync_templates(client: TestClient) -> None:
    assert (
        client.post(f"/v1/channels/{CHANNEL_A}/templates/sync", headers=auth(SALES_1)).status_code
        == 403
    )
    assert (
        client.post(f"/v1/channels/{CHANNEL_A}/templates/sync", headers=auth(MANAGER)).status_code
        == 403
    ), "settings.channels is owner and admin only"
    assert (
        client.post(f"/v1/channels/{CHANNEL_A}/templates/sync", headers=auth(OWNER)).status_code
        == 202
    )


def test_syncing_another_tenants_channel_is_not_found(client: TestClient) -> None:
    response = client.post(f"/v1/channels/{CHANNEL_B}/templates/sync", headers=auth(OWNER))
    assert response.status_code == 404
