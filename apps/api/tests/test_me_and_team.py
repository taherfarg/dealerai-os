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

from conftest import (
    MANAGER,
    OWNER,
    SALES_1,
    SALES_2,
    TEAM_EXPORT,
    TENANT_A,
    USER_A,
    reseed_with_people,
)
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


# --------------------------------------------------------------------------
# members and teams
# --------------------------------------------------------------------------


def test_members_list_shows_roles_names_and_availability(client: TestClient) -> None:
    response = client.get("/v1/members", headers=auth(MANAGER))
    assert response.status_code == 200, response.text
    members = response.json()
    assert {"owner", "manager", "sales"} <= {m["role"] for m in members}
    sales1 = next(m for m in members if m["id"] == str(SALES_1))
    assert sales1["name"] == "sales1"
    assert sales1["accepting_chats"] is True


def test_only_settings_team_may_change_a_member(client: TestClient) -> None:
    body = {"languages": ["ar", "fr"]}
    denied = client.patch(f"/v1/members/{SALES_2}", json=body, headers=auth(MANAGER))
    assert denied.status_code == 403, denied.text
    allowed = client.patch(f"/v1/members/{SALES_2}", json=body, headers=auth(OWNER))
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["languages"] == ["ar", "fr"]


def test_team_membership_is_replaced_not_appended(client: TestClient) -> None:
    body = {"team_ids": [str(TEAM_EXPORT)]}
    moved = client.patch(f"/v1/members/{SALES_2}", json=body, headers=auth(OWNER))
    assert moved.status_code == 200, moved.text
    assert moved.json()["team_ids"] == [str(TEAM_EXPORT)]


def test_the_last_owner_cannot_be_demoted(client: TestClient) -> None:
    """The seed has two owners: the first demotion is allowed, the second is not."""
    first = client.patch(f"/v1/members/{USER_A}", json={"role": "sales"}, headers=auth(OWNER))
    assert first.status_code == 200, first.text
    last = client.patch(f"/v1/members/{OWNER}", json={"role": "sales"}, headers=auth(OWNER))
    assert last.status_code == 409, last.text
    assert "owner" in last.json()["detail"].lower()


def test_an_unknown_role_is_refused_as_an_invalid_request(client: TestClient) -> None:
    """400, not 422: in this API 422 means a business rule refused a valid request
    (docs/07-api-design.md § 2); an unknown role is simply malformed."""
    body = {"role": "emperor"}
    response = client.patch(f"/v1/members/{SALES_2}", json=body, headers=auth(OWNER))
    assert response.status_code == 400, response.text
    assert response.json()["errors"][0]["field"] == "role"


def test_teams_can_be_created_and_listed(client: TestClient) -> None:
    body = {"name": "Aftersales", "member_ids": [str(SALES_2)]}
    created = client.post("/v1/teams", json=body, headers=auth(OWNER))
    assert created.status_code == 201, created.text
    listed = client.get("/v1/teams", headers=auth(MANAGER)).json()
    aftersales = next(team for team in listed if team["name"] == "Aftersales")
    assert aftersales["member_ids"] == [str(SALES_2)]


def test_a_manager_cannot_create_teams(client: TestClient) -> None:
    response = client.post("/v1/teams", json={"name": "Shadow"}, headers=auth(MANAGER))
    assert response.status_code == 403, response.text
