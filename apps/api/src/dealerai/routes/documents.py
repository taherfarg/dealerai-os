"""Knowledge documents: upload, list, remove. `settings.knowledge` throughout.

The file is stored and an event is emitted; extraction and embedding happen in
the worker. A 30-page export policy is not something to parse inside a request,
and the person who uploaded it should watch it turn from `pending` to `ready`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from pydantic import BaseModel

from ..core.errors import NotFound, Unusable
from ..db.session import tenant_session
from ..deps import TenantContext, require_permission
from ..events.bus import emit
from ..media import storage
from ..sales.knowledge import ACCEPTED

router = APIRouter(prefix="/v1/documents", tags=["documents"])

Ctx = Annotated[TenantContext, Depends(require_permission("settings.knowledge"))]

#: Bigger than any policy document a dealership has, small enough that a
#: mistaken video upload fails immediately rather than after four minutes.
MAX_BYTES = 20 * 1024 * 1024

#: The subset of documents.kind that a dealership uploads by hand. The column
#: allows more, written by other parts of the system.
KINDS = ("policy", "export_policy", "faq", "spec_sheet", "price_list", "other")

_RETURNING = "id, kind, title, status, error, created_at"


class Document(BaseModel):
    id: UUID
    kind: str
    title: str | None
    status: str
    error: str | None
    chunk_count: int
    created_at: datetime


@router.get("", response_model=list[Document])
async def list_documents(ctx: Ctx) -> list[dict[str, Any]]:
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        rows = await conn.fetch(
            """select d.id, d.kind, d.title, d.status, d.error, d.created_at,
                      (select count(*) from doc_chunks c where c.document_id = d.id) as chunk_count
                 from documents d where d.tenant_id = $1 order by d.created_at desc""",
            ctx.tenant_id,
        )
    return [dict(row) for row in rows]


@router.post("", response_model=Document, status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    ctx: Ctx,
    file: Annotated[UploadFile, File()],
    kind: Annotated[str, Form()] = "policy",
    title: Annotated[str | None, Form()] = None,
) -> dict[str, Any]:
    """Store it and queue the work. 202, because it is not readable yet."""
    if kind not in KINDS:
        raise Unusable(f"kind is one of {', '.join(KINDS)}")
    mime = file.content_type or "application/octet-stream"
    if mime not in ACCEPTED:
        raise Unusable("Upload a PDF, a Word file or a text file.")
    data = await file.read()
    if not data:
        raise Unusable("That file is empty.")
    if len(data) > MAX_BYTES:
        raise Unusable(f"That file is larger than {MAX_BYTES // (1024 * 1024)} MB.")

    path = storage.object_path(
        ctx.tenant_id, "documents", storage.extension_for(mime, file.filename)
    )
    await storage.upload(path, data, content_type=mime)

    async with (
        tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn,
        conn.transaction(),
    ):
        row = await conn.fetchrow(
            f"""insert into documents (tenant_id, kind, title, source, storage_path, status, meta)
                values ($1, $2, $3, 'upload', $4, 'pending', $5::jsonb)
                returning {_RETURNING}""",  # noqa: S608
            ctx.tenant_id,
            kind,
            title or file.filename,
            path,
            {"mime": mime, "bytes": len(data), "uploaded_by": str(ctx.user.id)},
        )
        await emit(
            conn,
            "document.uploaded",
            {"document_id": str(row["id"])},
            tenant_id=ctx.tenant_id,
            dedupe_key=f"document:{row['id']}",
        )
    return {**dict(row), "chunk_count": 0}


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(ctx: Ctx, document_id: UUID) -> None:
    """Chunks cascade. A document the dealer withdrew must stop being quoted."""
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        deleted = await conn.fetchval(
            "delete from documents where id = $1 returning id", document_id
        )
    if deleted is None:
        raise NotFound("no such document")
