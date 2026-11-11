"""Telling somebody something happened, in one place.

The bell, the tab title and web push all read the same rows, so where a
notification takes you — and whether it is worth a push — is decided here
rather than at each call site.
"""

from __future__ import annotations

from uuid import UUID

import asyncpg
import structlog

from ...config import get_settings
from ...core.words import Words
from ...db.session import tenant_session
from ...notifications import push
from ..bus import Event, emit, handler

log = structlog.get_logger()

#: entity type → where clicking the notification goes, relative to the tenant.
_HREFS: dict[str, str] = {
    "conversation": "/inbox/{id}",
    "contact": "/customers/{id}",
    "lead": "/pipeline?lead={id}",
    "task": "/tasks",
    "brief": "/dashboard",
}

#: What reaches a phone (docs/sales/07-frontend.md § 8): somebody is waiting on
#: you, a task fell due, a lead turned hot. The rest stays in the bell — a
#: customer's every message, and whatever arrives in batches.
PUSHED = frozenset(
    {"assigned", "waiting_due_soon", "waiting_missed", "unassigned_waiting", "task_due", "lead_hot"}
)


def href_for(entity: dict[str, str]) -> str | None:
    template = _HREFS.get(str(entity.get("type") or ""))
    return template.format(id=entity["id"]) if template and entity.get("id") else None


async def notify(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    user_id: UUID,
    kind: str,
    title: Words,
    body: Words | None = None,
    entity: dict[str, str] | None = None,
    dedupe_key: str | None = None,
) -> None:
    """One row, once — and, for the kinds worth interrupting somebody for, one
    push. `dedupe_key` is what makes "once" true across retries: a row that was
    already there asks for nothing.

    The words come in both languages and the row keeps one: its reader's, the
    language their browser last said (`profiles.locale`, migration 0015). They
    are not there to ask, and the push that follows carries the row as written.
    Somebody with no profile yet has not said, and is told in English.
    """
    entity = entity or {}
    notification_id = await conn.fetchval(
        """insert into notifications (tenant_id, user_id, kind, title, body, href, entity,
                                      dedupe_key)
           select $1::uuid, $2::uuid, $3::text,
                  case when p.locale = 'ar' then $5::text else $4::text end,
                  case when p.locale = 'ar' then $7::text else $6::text end,
                  $8::text, $9::jsonb, $10::text
             from (select 1) one left join profiles p on p.id = $2::uuid
           on conflict do nothing
           returning id""",
        tenant_id,
        user_id,
        kind,
        title.en,
        title.ar,
        body.en if body else None,
        body.ar if body else None,
        href_for(entity),
        entity,
        dedupe_key,
    )
    if notification_id is not None and kind in PUSHED:
        await emit(
            conn,
            "notification.push_requested",
            {"notification_id": str(notification_id)},
            tenant_id=tenant_id,
            dedupe_key=f"push:{notification_id}",
            priority=8,
        )


@handler("notification.push_requested")
async def on_push_requested(event: Event) -> None:
    """The notification, on every device its reader subscribed.

    Sent once: the push service does the retrying, for an hour (TTL), and a
    push later than that is worse than the bell it duplicates.
    """
    if event.tenant_id is None:
        raise ValueError("notification.push_requested requires a tenant")
    settings = get_settings()
    if not settings.vapid_private_key:
        log.info("push_skipped", because="VAPID_PRIVATE_KEY is not set")
        return
    notification_id = UUID(str(event.payload["notification_id"]))

    async with tenant_session(event.tenant_id) as conn:
        note = await conn.fetchrow(
            """select n.user_id, n.kind, n.title, n.body, n.href, t.slug
                 from notifications n join tenants t on t.id = n.tenant_id
                where n.id = $1""",
            notification_id,
        )
        if note is None:
            return
        devices = await conn.fetch(
            "select id, endpoint, p256dh, auth from push_subscriptions where user_id = $1",
            note["user_id"],
        )
    if not devices:
        return

    answers = await push.deliver(
        devices,
        push.message(
            note["title"],
            note["body"],
            href=f"/{note['slug']}{note['href'] or ''}",
            tag=note["kind"],
        ),
        private=settings.vapid_private_key,
        subject=settings.vapid_subject,
    )
    async with tenant_session(event.tenant_id) as conn:
        await push.record(conn, answers)
    log.info("pushed", kind=note["kind"], devices=len(devices))
