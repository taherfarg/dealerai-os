"""The browser calls the API directly now (docs/sales/01-architecture.md § 2 A),
so the API must answer cross-origin requests from the web app — and only from it."""

from __future__ import annotations

from fastapi.testclient import TestClient

from dealerai.main import app

PREFLIGHT = {
    "Access-Control-Request-Method": "GET",
    "Access-Control-Request-Headers": "authorization,x-tenant-id,idempotency-key",
}


def test_the_web_app_origin_is_allowed() -> None:
    with TestClient(app) as client:
        response = client.options(
            "/v1/me", headers={"Origin": "http://localhost:3000", **PREFLIGHT}
        )
    assert response.status_code == 200, response.text
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    allowed = response.headers["access-control-allow-headers"].lower()
    assert {"authorization", "x-tenant-id", "idempotency-key"} <= set(allowed.split(", "))


def test_any_other_origin_is_not() -> None:
    with TestClient(app) as client:
        response = client.options("/v1/me", headers={"Origin": "https://evil.example", **PREFLIGHT})
    assert "access-control-allow-origin" not in response.headers
