"""Quick replies: read by everyone, written by whoever holds settings.quick_replies."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from conftest import MANAGER, SALES_1, TENANT_A, TENANT_B, USER_B, reseed_with_people
from dealerai.config import get_settings
from dealerai.core.security import mint_test_token
from dealerai.main import app

SECRET = "super-secret-jwt-token-with-at-least-32-characters-long"
PRICE = {
    "shortcut": "/price",
    "title": "Price",
    "body": {"en": "Hello {name}, it is AED 128,000.", "ar": "مرحبا {name}، السعر 128,000 درهم."},
}


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "supabase_jwt_secret", SECRET)


@pytest.fixture
def client(_migrated: None) -> Iterator[TestClient]:
    asyncio.run(reseed_with_people())
    with TestClient(app) as test_client:
        yield test_client


def _auth(user_id: uuid.UUID, tenant_id: uuid.UUID = TENANT_A) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {mint_test_token(user_id, secret=SECRET)}",
        "X-Tenant-Id": str(tenant_id),
    }


def _add(client: TestClient, body: dict[str, Any], user: uuid.UUID = MANAGER) -> Any:
    return client.post("/v1/quick-replies", json=body, headers=_auth(user))


def test_everyone_reads_them_in_shortcut_order(client: TestClient) -> None:
    assert _add(client, PRICE).status_code == 201
    assert _add(client, {**PRICE, "shortcut": "/location", "title": "Where"}).status_code == 201
    listed = client.get("/v1/quick-replies", headers=_auth(SALES_1))
    assert listed.status_code == 200, listed.text
    assert [reply["shortcut"] for reply in listed.json()] == ["/location", "/price"]


def test_a_manager_adds_one_and_a_salesperson_cannot(client: TestClient) -> None:
    added = _add(client, PRICE)
    assert added.status_code == 201, added.text
    assert added.json()["body"] == {**PRICE["body"], "fr": None}
    assert _add(client, {**PRICE, "shortcut": "/mine"}, SALES_1).status_code == 403


def test_a_shortcut_is_a_slash_and_a_word(client: TestClient) -> None:
    response = _add(client, {**PRICE, "shortcut": "price"})
    assert response.status_code == 400
    assert response.json()["errors"][0]["field"] == "shortcut"


def test_two_replies_cannot_share_a_shortcut(client: TestClient) -> None:
    assert _add(client, PRICE).status_code == 201
    again = _add(client, PRICE)
    assert again.status_code == 409
    assert "/price" in again.json()["detail"]


def test_a_reply_with_no_text_in_any_language_is_refused(client: TestClient) -> None:
    response = _add(client, {**PRICE, "body": {"en": "  ", "ar": None}})
    assert response.status_code == 422
    assert response.json()["detail"] == "a quick reply needs its text in at least one language"


def test_saving_replaces_the_whole_reply(client: TestClient) -> None:
    """The form always sends all of it: a French body left out is a French body removed."""
    reply_id = _add(client, {**PRICE, "body": {**PRICE["body"], "fr": "Bonjour"}}).json()["id"]
    saved = client.patch(
        f"/v1/quick-replies/{reply_id}",
        json={**PRICE, "title": "Price today"},
        headers=_auth(MANAGER),
    )
    assert saved.status_code == 200, saved.text
    assert (saved.json()["title"], saved.json()["body"]["fr"]) == ("Price today", None)


def test_another_dealerships_reply_is_a_404(client: TestClient) -> None:
    theirs = client.post("/v1/quick-replies", json=PRICE, headers=_auth(USER_B, TENANT_B))
    assert theirs.status_code == 201, theirs.text
    reply_id = theirs.json()["id"]
    edited = client.patch(f"/v1/quick-replies/{reply_id}", json=PRICE, headers=_auth(MANAGER))
    assert edited.status_code == 404
    deleted = client.delete(f"/v1/quick-replies/{reply_id}", headers=_auth(MANAGER))
    assert deleted.status_code == 404
    assert client.get("/v1/quick-replies", headers=_auth(MANAGER)).json() == []
