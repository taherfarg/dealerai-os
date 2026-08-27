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
