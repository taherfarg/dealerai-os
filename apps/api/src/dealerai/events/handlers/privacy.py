"""A customer's right to be forgotten, and data that forgets itself.

`media.delete` removes the objects an erased row pointed at: SQL cannot reach
Storage, so `app.erase_contact` returns the paths and this finishes the job.
`sales.retention_due` is the nightly pass that makes the retention periods in
docs/sales/02-data-model.md § 7 true rather than written down.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog

from ...db.session import system_session, tenant_session
from ...media import storage
from ...sales.settings import SalesSettings
from ..bus import Event, emit, handler

log = structlog.get_logger()

#: docs/sales/02-data-model.md § 7.
NOTIFICATIONS_KEPT = timedelta(days=90)
BRIEFS_KEPT = timedelta(days=90)
WEBHOOKS_KEPT = timedelta(days=14)
#: A finished event holds what caused it — the raw inbound message included —
#: so it is kept as long as the webhook body it came from.
FINISHED_EVENTS_KEPT = WEBHOOKS_KEPT
#: ponytail: a backlog clears over several nights. Raise it if a first run
#: ever finds thousands.
ERASED_PER_NIGHT = 500

#: Nothing from them or to them for the retention period: the later of when
#: we last saw them and the last message in any of their conversations.
STALE_CUSTOMERS = """
select ct.id
  from contacts ct
 where greatest(ct.last_seen_at,
                coalesce((select max(cv.last_message_at) from conversations cv
                           where cv.contact_id = ct.id), ct.last_seen_at))
       < now() - make_interval(months => $1)
 order by ct.last_seen_at
 limit $2
"""


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


@handler("sales.retention_due")
async def on_retention_due(event: Event) -> None:
    """Make the retention periods true.

    Customers go whole, through the same function as an owner's DELETE.
    Notifications and briefs go by age. And raw webhook bodies — which hold
    message text and phone numbers, and are the one copy an erasure cannot
    find — go after fourteen days.
    """
    if event.tenant_id is None:
        raise ValueError("sales.retention_due requires a tenant")
    tenant_id = event.tenant_id
    now = datetime.now(UTC)
    async with tenant_session(tenant_id) as conn:
        raw = await conn.fetchval("select sales_settings from tenants where id = $1", tenant_id)
        months = SalesSettings.model_validate(raw or {}).retention_months
        stale = [row["id"] for row in await conn.fetch(STALE_CUSTOMERS, months, ERASED_PER_NIGHT)]

    paths: list[str] = []
    for contact_id in stale:
        # A transaction each: one customer who fails to erase must not keep
        # the rest another night.
        async with tenant_session(tenant_id) as conn:
            erased = await conn.fetchval(
                "select app.erase_contact($1, null, 'retention')", contact_id
            )
            paths.extend(erased or [])

    async with tenant_session(tenant_id) as conn:
        await conn.execute(
            "delete from notifications where created_at < $1", now - NOTIFICATIONS_KEPT
        )
        await conn.execute("delete from sales_briefs where created_at < $1", now - BRIEFS_KEPT)
        if paths:
            await emit(conn, "media.delete", {"paths": paths}, tenant_id=tenant_id)
    async with system_session() as conn:
        # Written before a tenant is known, and events can have none, so no
        # tenant owns the old ones: every tenant's pass may delete them, and a
        # second delete finds none.
        await conn.execute(
            "delete from webhook_deliveries where received_at < $1", now - WEBHOOKS_KEPT
        )
        await conn.execute(
            """delete from events where status in ('done', 'failed')
                 and coalesce(processed_at, created_at) < $1""",
            now - FINISHED_EVENTS_KEPT,
        )
    log.info("retention_done", tenant_id=str(tenant_id), erased=len(stale))
