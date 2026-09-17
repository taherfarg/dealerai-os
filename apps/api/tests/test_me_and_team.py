"""/v1/me, members and teams.

Synchronous because TestClient is synchronous; database setup goes through
asyncio.run, as in every other route test in this repository.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from conftest import MANAGER, SALES_1, TENANT_A, reseed_with_people
from dealerai.config import get_settings
from dealerai.core.security import mint_test_token
from dealerai.main import app

SECRET = "super-secret-jwt-token-with-at-least-32-characters-long"


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "supabase_jwt_secret", SECRET)


@pytest.fixture
def client(_migrated: None) -> Iterator[TestClient]:
    asyncio.run(reseed_with_people())
    with TestClient(app) as c:
        yield c


def auth(user_id: uuid.UUID, tenant_id: uuid.UUID = TENANT_A) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {mint_test_token(user_id, secret=SECRET)}",
        "X-Tenant-Id": str(tenant_id),
    }


# --------------------------------------------------------------------------
# /v1/me
# --------------------------------------------------------------------------


def test_me_returns_who_i_am_and_what_i_may_do(client: TestClient) -> None:
    response = client.get("/v1/me", headers=auth(SALES_1))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["user"]["name"] == "sales1"
    assert body["role"] == "sales"
    assert body["scope"] == "own"
    assert "inbox.send" in body["permissions"]
    assert "contacts.reassign" not in body["permissions"]
    assert body["tenant"]["slug"] == "alpha"
    assert body["accepting_chats"] is True


def test_me_includes_the_teams_i_belong_to(client: TestClient) -> None:
    response = client.get("/v1/me", headers=auth(MANAGER))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["scope"] == "team"
    assert len(body["team_ids"]) == 1


def test_availability_can_be_switched_off_and_stays_off(client: TestClient) -> None:
    switched = client.patch("/v1/me", json={"accepting_chats": False}, headers=auth(SALES_1))
    assert switched.status_code == 200, switched.text
    assert switched.json()["accepting_chats"] is False
    assert client.get("/v1/me", headers=auth(SALES_1)).json()["accepting_chats"] is False
