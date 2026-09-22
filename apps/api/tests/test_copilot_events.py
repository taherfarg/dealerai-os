"""What the worker does with an uploaded document. The embedder is stubbed."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

import asyncpg
import pytest

from conftest import TENANT_A, TENANT_B
from dealerai.ai.models import EMBEDDING_DIMENSIONS
from dealerai.config import get_settings
from dealerai.db.session import tenant_session
from dealerai.events.bus import Event
from dealerai.events.handlers import copilot
from dealerai.media import storage

POLICY = (
    "# Export policy\n\n"
    "## Algeria\n\nA certificate of origin is required. The buyer pays customs.\n\n"
    "## Morocco\n\nShipping runs weekly from Jebel Ali.\n"
)


@pytest.fixture(autouse=True)
def _storage_on_disk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "storage_dir", str(tmp_path))


@pytest.fixture
def embedded(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Every batch the handler asked to embed, and a vector of the right width."""
    batches: list[list[str]] = []

    async def fake(texts: Sequence[str], **kwargs: Any) -> list[list[float]]:
        batches.append(list(texts))
        return [[0.1] * EMBEDDING_DIMENSIONS for _ in texts]

    monkeypatch.setattr(copilot, "embed", fake)
    return batches


@pytest.fixture
async def document(su: asyncpg.Connection, seeded: None) -> AsyncIterator[uuid.UUID]:
    path = storage.object_path(TENANT_A, "documents", "txt")
    await storage.upload(path, POLICY.encode(), content_type="text/plain")
    document_id = await su.fetchval(
        """insert into documents (tenant_id, kind, title, source, storage_path, status, meta)
           values ($1, 'export_policy', 'Export policy', 'upload', $2, 'pending',
                   '{"mime": "text/plain"}'::jsonb)
           returning id""",
        TENANT_A,
        path,
    )
    yield uuid.UUID(str(document_id))


def _event(document_id: uuid.UUID) -> Event:
    return Event(
        id=1,
        tenant_id=TENANT_A,
        event_type="document.uploaded",
        payload={"document_id": str(document_id)},
        attempts=1,
        dedupe_key=None,
    )


async def _document(su: asyncpg.Connection, document_id: uuid.UUID) -> asyncpg.Record:
    row = await su.fetchrow(
        "select status, error, content from documents where id = $1", document_id
    )
    assert row is not None
    return row


async def _chunks(su: asyncpg.Connection, document_id: uuid.UUID) -> list[asyncpg.Record]:
    return await su.fetch(  # type: ignore[no-any-return]
        """select chunk_index, content, meta->>'heading' as heading,
                  embedding is not null as embedded
             from doc_chunks where document_id = $1 order by chunk_index""",
        document_id,
    )


async def test_a_document_becomes_paragraphs_with_vectors(
    db: None, su: asyncpg.Connection, document: uuid.UUID, embedded: list[list[str]]
) -> None:
    await copilot.on_document_uploaded(_event(document))

    assert (await _document(su, document))["status"] == "ready"
    chunks = await _chunks(su, document)
    assert [chunk["heading"] for chunk in chunks] == [
        "Export policy › Algeria",
        "Export policy › Morocco",
    ]
    assert all(chunk["embedded"] for chunk in chunks)


async def test_what_is_embedded_carries_its_heading(
    db: None, document: uuid.UUID, embedded: list[list[str]]
) -> None:
    """The paragraph is stored without the heading and embedded with it: one is
    what a draft quotes, the other is what makes it findable."""
    await copilot.on_document_uploaded(_event(document))
    assert embedded[0][0].startswith("Export policy › Algeria")


async def test_a_failed_document_says_why_on_the_row(
    db: None, su: asyncpg.Connection, seeded: None, embedded: list[list[str]]
) -> None:
    """Settings shows this sentence. A worker log line is not an answer."""
    path = storage.object_path(TENANT_A, "documents", "pdf")
    await storage.upload(path, b"%PDF-1.4 truncated", content_type="application/pdf")
    document_id = await su.fetchval(
        """insert into documents (tenant_id, kind, source, storage_path, status, meta)
           values ($1, 'policy', 'upload', $2, 'pending', '{"mime": "application/pdf"}'::jsonb)
           returning id""",
        TENANT_A,
        path,
    )
    await copilot.on_document_uploaded(_event(uuid.UUID(str(document_id))))

    row = await _document(su, uuid.UUID(str(document_id)))
    assert row["status"] == "failed"
    assert "could not be read" in row["error"]
    assert embedded == []  # nothing was paid for


async def test_a_document_with_no_text_in_it_fails_with_a_sentence(
    db: None, su: asyncpg.Connection, seeded: None, embedded: list[list[str]]
) -> None:
    path = storage.object_path(TENANT_A, "documents", "txt")
    await storage.upload(path, b"   \n\n  ", content_type="text/plain")
    document_id = await su.fetchval(
        """insert into documents (tenant_id, kind, source, storage_path, status, meta)
           values ($1, 'policy', 'upload', $2, 'pending', '{"mime": "text/plain"}'::jsonb)
           returning id""",
        TENANT_A,
        path,
    )
    await copilot.on_document_uploaded(_event(uuid.UUID(str(document_id))))
    assert "no text" in (await _document(su, uuid.UUID(str(document_id))))["error"]


async def test_reprocessing_replaces_the_chunks_rather_than_adding_to_them(
    db: None, su: asyncpg.Connection, document: uuid.UUID, embedded: list[list[str]]
) -> None:
    """Old paragraphs left behind would be quoted alongside the new ones."""
    await copilot.on_document_uploaded(_event(document))
    first = await _chunks(su, document)

    await su.execute("update documents set status = 'pending' where id = $1", document)
    await copilot.on_document_uploaded(_event(document))
    assert len(await _chunks(su, document)) == len(first)


async def test_a_document_already_processed_is_left_alone(
    db: None, su: asyncpg.Connection, document: uuid.UUID, embedded: list[list[str]]
) -> None:
    """The queue retries; re-embedding a ready document is money for nothing."""
    await copilot.on_document_uploaded(_event(document))
    await copilot.on_document_uploaded(_event(document))
    assert len(embedded) == 1


async def test_a_document_deleted_while_queued_is_not_an_error(
    db: None, seeded: None, embedded: list[list[str]]
) -> None:
    await copilot.on_document_uploaded(_event(uuid.uuid4()))  # does not raise
    assert embedded == []


async def test_another_workspace_cannot_be_given_our_chunks(
    db: None, su: asyncpg.Connection, document: uuid.UUID, embedded: list[list[str]]
) -> None:
    await copilot.on_document_uploaded(_event(document))
    async with tenant_session(TENANT_B) as conn:
        assert await conn.fetchval("select count(*) from doc_chunks") == 0
