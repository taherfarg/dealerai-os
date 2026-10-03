"""Boots the real app through its lifespan, so this covers pool startup too."""

from __future__ import annotations

from fastapi.testclient import TestClient

from dealerai.main import app


def test_health_reports_ok() -> None:
    with TestClient(app) as client:
        response = client.get("/internal/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"


def test_errors_are_problem_json() -> None:
    with TestClient(app) as client:
        response = client.get("/does-not-exist")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["type"].endswith("/not-found")
    assert body["instance"] == "/does-not-exist"
    assert body["trace_id"]


def test_trace_id_is_echoed_back() -> None:
    with TestClient(app) as client:
        response = client.get("/internal/health", headers={"X-Trace-Id": "abc123"})
    assert response.headers["X-Trace-Id"] == "abc123"


def test_health_says_how_far_behind_the_worker_is() -> None:
    """With a worker running, what is due is nothing, or seconds old. With none
    it only grows — and this is how anybody outside the process can tell."""
    import asyncio

    import asyncpg

    from dealerai.config import get_settings

    async def queue(sql: str) -> None:
        conn = await asyncpg.connect(get_settings().database_url)
        try:
            await conn.execute(sql)
        finally:
            await conn.close()

    asyncio.run(
        queue(
            """insert into events (event_type, run_after) values
                 ('health.probe', now() - interval '2 minutes'),
                 ('health.probe', now() + interval '1 hour')"""
        )
    )
    try:
        with TestClient(app) as client:
            body = client.get("/internal/health").json()
        assert body["queue"]["waiting"] >= 1
        assert body["queue"]["oldest_seconds"] >= 120
        # What is not due yet is not late.
        assert body["queue"]["oldest_seconds"] < 3600 or body["queue"]["waiting"] > 1
    finally:
        asyncio.run(queue("delete from events where event_type = 'health.probe'"))
