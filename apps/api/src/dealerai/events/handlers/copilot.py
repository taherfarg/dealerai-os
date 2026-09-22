"""Everything the copilot does when nobody asked it to.

One handler per event: a document was uploaded, a customer wrote, a
conversation went quiet, an hour passed.
"""

from __future__ import annotations

from uuid import UUID

import structlog

from ...ai.embeddings import embed, literal
from ...db.session import tenant_session
from ...media import storage
from ...sales.knowledge import chunk, embeddable, extract
from ..bus import Event, handler

log = structlog.get_logger()

#: Kept in the document row rather than only in the log: the person who
#: uploaded it is looking at Settings, not at the worker's output.
_MAX_ERROR = 500

#: Enough of the text to show a preview and to search; the chunks are what
#: retrieval actually reads.
_MAX_CONTENT = 100_000


@handler("document.uploaded")
async def on_document_uploaded(event: Event) -> None:
    """Extract, chunk, embed."""
    if event.tenant_id is None:
        raise ValueError("document.uploaded requires a tenant")
    tenant_id = event.tenant_id
    document_id = UUID(str(event.payload["document_id"]))

    async with tenant_session(tenant_id) as conn:
        row = await conn.fetchrow(
            """update documents set status = 'processing', error = null
                where id = $1 and status in ('pending', 'failed')
                returning storage_path, meta, title""",
            document_id,
        )
    if row is None:
        return  # already processed, or deleted while it sat in the queue

    try:
        data = await storage.download(str(row["storage_path"]))
        text = extract(data, str((row["meta"] or {}).get("mime") or ""), row["title"])
        pieces = chunk(text)
        if not pieces:
            raise ValueError("no text could be read from this file")
        vectors = await embed(
            [embeddable(piece) for piece in pieces], tenant_id=tenant_id, kind="document"
        )
    except Exception as exc:  # noqa: BLE001 - every failure is the dealer's to see
        async with tenant_session(tenant_id) as conn:
            await conn.execute(
                "update documents set status = 'failed', error = $2 where id = $1",
                document_id,
                str(exc)[:_MAX_ERROR],
            )
        log.warning("document_failed", document_id=str(document_id), error=str(exc))
        return

    async with tenant_session(tenant_id) as conn, conn.transaction():
        # Replaced wholesale rather than appended: re-processing a document must
        # not leave the old chunks behind to be quoted alongside the new ones.
        await conn.execute("delete from doc_chunks where document_id = $1", document_id)
        await conn.executemany(
            """insert into doc_chunks
                 (tenant_id, document_id, chunk_index, content, embedding, meta)
               values ($1,$2,$3,$4,$5::vector,$6::jsonb)""",
            [
                (
                    tenant_id,
                    document_id,
                    piece.index,
                    piece.content,
                    literal(vector),
                    {"heading": piece.heading},
                )
                for piece, vector in zip(pieces, vectors, strict=True)
            ],
        )
        await conn.execute(
            "update documents set status = 'ready', content = $2 where id = $1",
            document_id,
            text[:_MAX_CONTENT],
        )
    log.info("document_ready", document_id=str(document_id), chunks=len(pieces))
