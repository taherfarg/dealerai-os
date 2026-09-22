"""Uploading the dealership's own documents, and who may."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient

from conftest import MANAGER, OWNER, SALES_1, TENANT_A, TENANT_B, reseed_with_people
from dealerai.config import get_settings
from dealerai.core.security import mint_test_token
from dealerai.main import app

SECRET = "super-secret-jwt-token-with-at-least-32-characters-long"
POLICY = b"# Export policy\n\nShipping is arranged by the buyer.\n"


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "supabase_jwt_secret", SECRET)


@pytest.fixture(autouse=True)
def _storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "storage_dir", str(tmp_path))


def _auth(user_id: uuid.UUID, tenant_id: uuid.UUID = TENANT_A) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {mint_test_token(user_id, secret=SECRET)}",
        "X-Tenant-Id": str(tenant_id),
    }


def _upload(
    client: TestClient,
    user_id: uuid.UUID = OWNER,
    *,
    data: bytes = POLICY,
    mime: str = "text/plain",
    name: str = "export.txt",
    kind: str = "export_policy",
) -> Any:
    return client.post(
        "/v1/documents",
        files={"file": (name, data, mime)},
        data={"kind": kind},
        headers=_auth(user_id),
    )


@pytest.fixture
def client() -> Iterator[TestClient]:
    asyncio.run(reseed_with_people())
    with TestClient(app) as test_client:
        yield test_client


async def _query(sql: str, *args: Any) -> Any:
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        return await conn.fetch(sql, *args)
    finally:
        await conn.close()


def test_uploading_queues_the_work_rather_than_doing_it(client: TestClient) -> None:
    """A 30-page PDF parsed inside the request is a request that times out."""
    response = _upload(client)
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending"
    assert body["chunk_count"] == 0
    assert body["title"] == "export.txt"

    queued = asyncio.run(
        _query(
            "select payload from events where event_type = 'document.uploaded' and tenant_id = $1",
            TENANT_A,
        )
    )
    assert len(queued) == 1


def test_a_manager_cannot_upload_a_policy(client: TestClient) -> None:
    """Knowledge is owner and admin only: a document is what every draft quotes."""
    assert _upload(client, MANAGER).status_code == 403


def test_a_salesperson_cannot_upload_a_policy(client: TestClient) -> None:
    assert _upload(client, SALES_1).status_code == 403


def test_a_video_is_refused_before_it_is_stored(client: TestClient) -> None:
    response = _upload(client, data=b"\x00\x00", mime="video/mp4", name="walkaround.mp4")
    assert response.status_code == 422
    assert "PDF" in response.json()["detail"]


def test_an_empty_file_is_refused(client: TestClient) -> None:
    assert _upload(client, data=b"").status_code == 422


def test_a_kind_nobody_uploads_is_refused_with_the_list(client: TestClient) -> None:
    response = _upload(client, kind="transcript")
    assert response.status_code == 422
    assert "export_policy" in response.json()["detail"]


def test_the_list_says_what_became_of_each_one(client: TestClient) -> None:
    _upload(client)
    rows = client.get("/v1/documents", headers=_auth(OWNER)).json()
    assert [row["kind"] for row in rows] == ["export_policy"]
    assert rows[0]["error"] is None


def test_another_workspaces_documents_are_not_listed(client: TestClient) -> None:
    _upload(client)
    assert client.get("/v1/documents", headers=_auth(OWNER, TENANT_B)).status_code in (403, 404)


def test_deleting_a_document_takes_its_chunks_with_it(client: TestClient) -> None:
    """A document the dealer withdrew must stop being quoted immediately."""
    document_id = _upload(client).json()["id"]
    asyncio.run(
        _query(
            """insert into doc_chunks (tenant_id, document_id, chunk_index, content)
               values ($1, $2, 0, 'By sea.')""",
            TENANT_A,
            uuid.UUID(document_id),
        )
    )
    assert client.delete(f"/v1/documents/{document_id}", headers=_auth(OWNER)).status_code == 204
    left = asyncio.run(
        _query("select 1 from doc_chunks where document_id = $1", uuid.UUID(document_id))
    )
    assert left == []


def test_a_document_that_is_not_there_is_a_404(client: TestClient) -> None:
    response = client.delete(f"/v1/documents/{uuid.uuid4()}", headers=_auth(OWNER))
    assert response.status_code == 404
