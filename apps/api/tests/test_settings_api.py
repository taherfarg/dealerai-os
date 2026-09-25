"""The dealership's sales settings: read by everyone, changed by the right person."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Iterator
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient

from conftest import MANAGER, OWNER, SALES_1, TEAM_LOCAL, TENANT_A, reseed_with_people
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
    with TestClient(app) as test_client:
        yield test_client


def _auth(user_id: uuid.UUID) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {mint_test_token(user_id, secret=SECRET)}",
        "X-Tenant-Id": str(TENANT_A),
    }


def _settings(client: TestClient, user: uuid.UUID = SALES_1) -> dict[str, Any]:
    response = client.get("/v1/settings/sales", headers=_auth(user))
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


def _change(client: TestClient, user: uuid.UUID, body: dict[str, Any]) -> Any:
    return client.patch("/v1/settings/sales", json=body, headers=_auth(user))


async def _sql(sql: str, *args: object) -> Any:
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        return await conn.fetchval(sql, *args)
    finally:
        await conn.close()


def test_everyone_reads_the_settings_with_the_defaults_filled_in(client: TestClient) -> None:
    settings = _settings(client)
    assert (
        settings["first_response_target_min"],
        settings["drafts_enabled"],
        settings["arabic_register"],
        settings["retention_months"],
    ) == (5, True, "mirror", 24)


def test_a_manager_moves_the_opening_hours(client: TestClient) -> None:
    response = _change(
        client, MANAGER, {"business_hours": {"mon": {"open": "09:00", "close": "21:00"}}}
    )
    assert response.status_code == 200, response.text
    assert _settings(client)["business_hours"] == {"mon": {"open": "09:00:00", "close": "21:00:00"}}


def test_a_manager_may_not_switch_the_ai_off(client: TestClient) -> None:
    response = _change(client, MANAGER, {"drafts_enabled": False})
    assert response.status_code == 403
    assert "settings.ai" in response.json()["detail"]
    assert _settings(client)["drafts_enabled"] is True


def test_a_salesperson_changes_nothing(client: TestClient) -> None:
    assert _change(client, SALES_1, {"first_response_target_min": 10}).status_code == 403


def test_absent_leaves_the_default_team_and_null_clears_it(client: TestClient) -> None:
    assert _change(client, OWNER, {"default_team_id": str(TEAM_LOCAL)}).status_code == 200
    kept = _change(client, OWNER, {"first_response_target_min": 7}).json()
    assert kept["default_team_id"] == str(TEAM_LOCAL)
    cleared = _change(client, OWNER, {"default_team_id": None}).json()
    assert cleared["default_team_id"] is None


def test_routing_to_a_team_that_does_not_exist_is_refused(client: TestClient) -> None:
    rule = {"languages": ["fr"], "team_id": str(uuid.uuid4())}
    response = _change(client, OWNER, {"routing_rules": [rule]})
    assert response.status_code == 422
    assert response.json()["detail"] == "routing names a team that does not exist"


def test_hours_that_close_before_they_open_are_refused_by_field(client: TestClient) -> None:
    """The screen checks this before saving; the API is the backstop."""
    response = _change(
        client, MANAGER, {"business_hours": {"mon": {"open": "18:00", "close": "09:00"}}}
    )
    assert response.status_code == 400
    assert response.json()["errors"][0]["field"] == "business_hours.mon.close"


def test_a_key_nobody_may_write_is_refused(client: TestClient) -> None:
    """Scoring weights have no screen in Phase 1 and are set by hand (04 § 5)."""
    response = _change(client, OWNER, {"scoring_weights": {"visit": 50}})
    assert response.status_code == 400
    assert response.json()["errors"][0]["field"] == "scoring_weights"


def test_a_key_a_newer_version_wrote_survives_a_save(client: TestClient) -> None:
    asyncio.run(
        _sql(
            """update tenants set sales_settings = '{"future_key": 1}'::jsonb where id = $1""",
            TENANT_A,
        )
    )
    assert _change(client, OWNER, {"first_response_target_min": 6}).status_code == 200
    stored = json.loads(
        asyncio.run(_sql("select sales_settings from tenants where id = $1", TENANT_A))
    )
    assert (stored["future_key"], stored["first_response_target_min"]) == (1, 6)


async def _decided() -> None:
    """Four drafts about prices, decided four ways."""
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        conversation = await conn.fetchval(
            "select id from conversations where tenant_id = $1", TENANT_A
        )
        for outcome, ratio in (
            ("sent", 0.0),
            ("edited", 0.1),
            ("edited", 0.5),
            ("discarded", None),
        ):
            await conn.execute(
                """insert into ai_suggestions (tenant_id, conversation_id, status, text, intent,
                                               outcome, edit_ratio)
                   values ($1, $2, 'superseded', 'Hello', 'price', $3, $4)""",
                TENANT_A,
                conversation,
                outcome,
                ratio,
            )
    finally:
        await conn.close()


def test_acceptance_is_by_intent_and_counts_light_edits(client: TestClient) -> None:
    asyncio.run(_decided())
    response = client.get("/v1/settings/ai/acceptance", headers=_auth(OWNER))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["by_intent"] == [
        {
            "intent": "price",
            "decided": 4,
            "sent": 1,
            "lightly_edited": 1,
            "rewritten": 1,
            "discarded": 1,
            "rate": 0.5,
        }
    ]
    assert (body["overall"]["intent"], body["overall"]["rate"]) == (None, 0.5)


def test_acceptance_is_an_owners_question(client: TestClient) -> None:
    assert client.get("/v1/settings/ai/acceptance", headers=_auth(MANAGER)).status_code == 403
