"""What language a person reads the app in (S7 Part C).

The browser has always known. The server needs it for what it writes when
nobody is there to ask: a notification, and the push that follows it.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator

import asyncpg
import pytest
from fastapi.testclient import TestClient

from conftest import SALES_1, SALES_2, TENANT_A, USER_A, reseed_with_people
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


def auth(user_id: uuid.UUID) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {mint_test_token(user_id, secret=SECRET)}",
        "X-Tenant-Id": str(TENANT_A),
    }


def _reads(client: TestClient, user_id: uuid.UUID) -> str:
    response = client.get("/v1/me", headers=auth(user_id))
    assert response.status_code == 200, response.text
    return str(response.json()["locale"])


def _has_a_profile(user_id: uuid.UUID) -> bool:
    async def look() -> bool:
        conn = await asyncpg.connect(get_settings().migration_dsn)
        try:
            return bool(await conn.fetchval("select 1 from profiles where id = $1", user_id))
        finally:
            await conn.close()

    return asyncio.run(look())


def test_a_person_reads_english_until_they_say_otherwise(client: TestClient) -> None:
    assert _reads(client, SALES_1) == "en"


def test_a_person_says_what_they_read(client: TestClient) -> None:
    response = client.put("/v1/me/locale", json={"locale": "ar"}, headers=auth(SALES_1))
    assert response.status_code == 204, response.text

    assert _reads(client, SALES_1) == "ar"
    assert _reads(client, SALES_2) == "en", "nobody else's changed"


def test_only_a_language_the_app_speaks(client: TestClient) -> None:
    response = client.put("/v1/me/locale", json={"locale": "fr"}, headers=auth(SALES_1))
    assert response.status_code == 400, response.text
    assert _reads(client, SALES_1) == "en"


def test_somebody_with_no_profile_yet_gets_one(client: TestClient) -> None:
    """An owner who signed up before profiles were written has a membership and
    no profile. They read English until they say, and saying makes the row."""
    assert not _has_a_profile(USER_A)
    assert _reads(client, USER_A) == "en"

    response = client.put("/v1/me/locale", json={"locale": "ar"}, headers=auth(USER_A))
    assert response.status_code == 204, response.text

    assert _has_a_profile(USER_A)
    assert _reads(client, USER_A) == "ar"


def test_saying_it_twice_changes_nothing_else(client: TestClient) -> None:
    client.put("/v1/me/locale", json={"locale": "ar"}, headers=auth(SALES_1))
    client.put("/v1/me/locale", json={"locale": "ar"}, headers=auth(SALES_1))
    body = client.get("/v1/me", headers=auth(SALES_1)).json()
    assert (body["locale"], body["user"]["name"]) == ("ar", "sales1")
