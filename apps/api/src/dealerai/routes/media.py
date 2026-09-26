"""Serving a stored object to a browser that holds a signed link."""

from __future__ import annotations

import mimetypes

from fastapi import APIRouter, Response

from ..media import storage
from ..media.links import verify

router = APIRouter(prefix="/v1/media", tags=["media"])


@router.get("/{token}")
async def get_object(token: str) -> Response:
    """No X-Tenant-Id and no bearer token: the link itself is the authorisation.

    > ponytail: the whole object is read into memory before it is answered.
    > WhatsApp caps media at 100 MB and a dealer's are photos and voice notes.
    > Upgrade trigger: video attachments in real use — then stream it through.
    """
    storage_path = verify(token)
    data = await storage.download(storage_path)
    mime, _ = mimetypes.guess_type(storage_path)
    return Response(
        content=data,
        media_type=mime or "application/octet-stream",
        headers={
            # Private: a shared cache must not keep one customer's voice note.
            "Cache-Control": "private, max-age=3600",
            "Content-Disposition": "inline",
        },
    )
