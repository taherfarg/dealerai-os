"""A person's devices over HTTP: subscribing one, listing them, removing one,
and a push to try them with."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from conftest import (
    PHONE,
    SALES_1,
    SALES_2,
    TENANT_A,
    PushService,
    open_push,
    reseed_with_people,
)
from dealerai.config import get_settings
from dealerai.core.security import mint_test_token
from dealerai.main import app
from dealerai.notifications import push

SECRET = "super-secret-jwt-token-with-at-least-32-characters-long"
SUBSCRIPTION = {**PHONE, "user_agent": "Mozilla/5.0 (Linux; Android 14) Chrome/130.0 Mobile"}
LAPTOP = {**SUBSCRIPTION, "endpoint": "https://fcm.googleapis.com/fcm/send/the-laptop"}
#: 65 bytes starting with 4, as an uncompressed point does — and on no curve.
OFF_THE_CURVE = push.b64(bytes([4]) + bytes([1]) * 64)


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "supabase_jwt_secret", SECRET)


@pytest.fixture
def client(_migrated: None, push_service: PushService) -> Iterator[TestClient]:
    asyncio.run(reseed_with_people())
    with TestClient(app) as test_client:
        yield test_client


def _auth(user_id: uuid.UUID) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {mint_test_token(user_id, secret=SECRET)}",
        "X-Tenant-Id": str(TENANT_A),
    }


def _subscribe(
    client: TestClient, body: dict[str, str] = SUBSCRIPTION, user: uuid.UUID = SALES_1
) -> Any:
    return client.post("/v1/push-subscriptions", json=body, headers=_auth(user))


def _devices(client: TestClient, user: uuid.UUID = SALES_1) -> list[dict[str, Any]]:
    listed = client.get("/v1/push-subscriptions", headers=_auth(user))
    assert listed.status_code == 200, listed.text
    return listed.json()  # type: ignore[no-any-return]


def test_the_key_a_browser_subscribes_with(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    answer = client.get("/v1/push/key", headers=_auth(SALES_1))
    assert answer.status_code == 200, answer.text
    point = push.unb64(answer.json()["public_key"])
    assert len(point) == 65 and point[0] == 4, "the uncompressed point, never the private half"

    monkeypatch.setattr(get_settings(), "vapid_private_key", None)
    refused = client.get("/v1/push/key", headers=_auth(SALES_1))
    assert refused.status_code == 503
    assert refused.json()["type"].endswith("/push-unavailable")


def test_a_device_subscribes_and_is_listed_to_its_owner_only(client: TestClient) -> None:
    added = _subscribe(client)
    assert added.status_code == 201, added.text

    [mine] = _devices(client)
    assert mine["id"] == added.json()["id"]
    assert mine["user_agent"] == SUBSCRIPTION["user_agent"] and mine["last_success_at"] is None
    assert not {"endpoint", "p256dh", "auth"} & mine.keys(), "the address and keys never come back"
    assert _devices(client, SALES_2) == []


def test_subscribing_again_replaces_rather_than_adds(client: TestClient) -> None:
    _subscribe(client)
    assert _subscribe(client).status_code == 201
    assert len(_devices(client)) == 1


def test_a_device_changes_hands(client: TestClient) -> None:
    """The same browser, somebody else signed in: it is theirs now."""
    _subscribe(client)
    assert _subscribe(client, user=SALES_2).status_code == 201
    assert _devices(client) == []
    assert len(_devices(client, SALES_2)) == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("p256dh", "AAAA"),
        ("p256dh", PHONE["auth"]),
        ("p256dh", "!!not base64!!"),
        # The right length and the right first byte, and not a point on the curve.
        ("p256dh", OFF_THE_CURVE),
        ("auth", "AAAA"),
        ("auth", PHONE["p256dh"]),
    ],
)
def test_keys_that_are_not_keys_are_refused(client: TestClient, field: str, value: str) -> None:
    refused = _subscribe(client, {**SUBSCRIPTION, field: value})
    assert refused.status_code == 400, refused.text
    assert refused.json()["errors"][0]["field"] == field
    assert _devices(client) == []


@pytest.mark.parametrize(
    "endpoint",
    ["https://localhost:8000/v1/tenants", "http://fcm.googleapis.com/fcm/send/abc", "nowhere"],
)
def test_an_address_that_is_no_push_service_is_refused(client: TestClient, endpoint: str) -> None:
    """The worker POSTs to this address: nobody gets to choose where."""
    refused = _subscribe(client, {**SUBSCRIPTION, "endpoint": endpoint})
    assert refused.status_code == 422, refused.text
    assert _devices(client) == []


def test_nothing_is_subscribed_on_a_server_with_no_key(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "vapid_private_key", None)
    assert _subscribe(client).status_code == 503


def test_removing_a_device(client: TestClient) -> None:
    device = _subscribe(client).json()["id"]
    path = f"/v1/push-subscriptions/{device}"

    assert client.delete(path, headers=_auth(SALES_2)).status_code == 404
    assert len(_devices(client)) == 1, "somebody else's is not theirs to remove"

    assert client.delete(path, headers=_auth(SALES_1)).status_code == 204
    assert _devices(client) == []
    assert client.delete(path, headers=_auth(SALES_1)).status_code == 404


def test_a_test_push_goes_to_my_devices_now(client: TestClient, push_service: PushService) -> None:
    _subscribe(client)
    _subscribe(client, LAPTOP, SALES_2)

    sent = client.post("/v1/push-subscriptions/test", headers=_auth(SALES_1))

    assert sent.status_code == 200, sent.text
    assert sent.json() == {"sent": 1, "failed": 0}
    [request] = push_service.requests
    assert str(request.url) == PHONE["endpoint"], "mine, and nobody else's"
    said = open_push(request.content)
    assert said["title"] == "DealerAI" and said["href"] == "/alpha/settings/notifications"
    assert _devices(client)[0]["last_success_at"] is not None


def test_a_test_push_forgets_a_device_that_is_gone(
    client: TestClient, push_service: PushService
) -> None:
    _subscribe(client)
    push_service.status = 410

    sent = client.post("/v1/push-subscriptions/test", headers=_auth(SALES_1))

    assert sent.json() == {"sent": 0, "failed": 1}
    assert _devices(client) == []


def test_a_test_push_with_no_device_says_so(client: TestClient, push_service: PushService) -> None:
    sent = client.post("/v1/push-subscriptions/test", headers=_auth(SALES_1))
    assert sent.json() == {"sent": 0, "failed": 0}
    assert push_service.requests == []
