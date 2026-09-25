"""A customer's right to be forgotten, and data that forgets itself.

`media.delete` removes the objects an erased row pointed at: SQL cannot reach
Storage, so `app.erase_contact` returns the paths and this finishes the job.
`sales.retention_due` is the nightly pass that makes the retention periods in
docs/sales/02-data-model.md § 7 true rather than written down.
"""

from __future__ import annotations

import structlog

from ...media import storage
from ..bus import Event, handler

log = structlog.get_logger()


@handler("media.delete")
async def on_media_delete(event: Event) -> None:
    """Only this tenant's objects. Every path starts with the tenant id
    (storage.object_path), so a path that does not is refused and logged,
    whatever wrote the event."""
    if event.tenant_id is None:
        raise ValueError("media.delete requires a tenant")
    prefix = f"{event.tenant_id}/"
    paths = [str(path) for path in event.payload.get("paths") or []]
    foreign = [path for path in paths if not path.startswith(prefix)]
    if foreign:
        log.error("media_delete_refused", tenant_id=str(event.tenant_id), count=len(foreign))
    await storage.remove([path for path in paths if path.startswith(prefix)])
