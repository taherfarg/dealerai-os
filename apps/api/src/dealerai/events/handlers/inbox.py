"""Inbox handlers: assignment, notifications and the response-target check."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import asyncpg
import structlog

from ...db.session import tenant_session
from ...sales.assignment import Candidate, choose, route_to_team
from ...sales.settings import SalesSettings
from ..bus import Event, emit, handler
from .notify import notify

log = structlog.get_logger()

#: Managers sell too in a dealership this size; `accepting_chats` is what decides
#: availability, not the role.
_CANDIDATES = """
select m.user_id, m.languages, m.accepting_chats, m.max_open_conversations, m.last_assigned_at,
       (select count(*) from conversations c
         where c.assigned_to = m.user_id and c.status = 'open')        as open_conversations
from memberships m
join team_members tm on tm.user_id = m.user_id and tm.tenant_id = m.tenant_id
where m.tenant_id = $1 and tm.team_id = $2 and m.role in ('sales', 'manager')
"""

#: Taken rather than waited for: if someone else is assigning to this person right
#: now, we move to the next candidate instead of queueing behind them.
_CLAIM_MEMBER = """
select user_id from memberships
where tenant_id = $1 and user_id = $2
for update skip locked
"""

_ASSIGN = """
update conversations set assigned_to = $2, owner_id = coalesce(owner_id, $2)
where id = $1 and assigned_to is null
returning contact_id, assigned_to
"""

_TEAM_MANAGERS = """
select m.user_id from memberships m
join team_members tm on tm.user_id = m.user_id and tm.tenant_id = m.tenant_id
where m.tenant_id = $1 and tm.team_id = $2 and m.role = 'manager'
"""

_ADMINS = """
select user_id from memberships where tenant_id = $1 and role in ('owner', 'admin')
"""

#: kind -> (title, body). The words live here rather than in the emitters, so a
#: notification reads the same wherever it was raised.
_NOTIFICATIONS: dict[str, tuple[str, str | None]] = {
    "message_received": ("New message", None),
    "assigned": ("A customer is waiting for you", None),
    "waiting_due_soon": ("A customer is about to wait too long", None),
    "waiting_missed": ("A customer has been waiting too long", None),
    "unassigned_waiting": ("An unassigned customer is waiting", None),
    "template_rejected": ("WhatsApp rejected a template", "Open Settings → Channels to fix it."),
    "channel_disconnected": ("WhatsApp was disconnected", "Reconnect it in Settings → Channels."),
    "channel_quality": ("WhatsApp flagged this number's quality", None),
}


async def _event_line(
    conn: asyncpg.Connection, tenant_id: UUID, conversation_id: UUID, kind: str, text: str
) -> None:
    """A grey line in the thread: a conversation's history belongs in the thread,
    not in an audit nobody opens."""
    await conn.execute(
        """insert into messages (tenant_id, conversation_id, kind, type, direction, sender,
                                 origin, event)
           values ($1, $2, 'event', 'text', 'out', 'system', 'system', $3)""",
        tenant_id,
        conversation_id,
        {"type": kind, "text": text},
    )


@handler("conversation.assign_requested")
async def on_assign_requested(event: Event) -> None:
    """Give a waiting conversation to someone, or leave it in the team's queue."""
    if event.tenant_id is None:
        raise ValueError("conversation.assign_requested requires a tenant")
    tenant_id = event.tenant_id
    conversation_id = UUID(str(event.payload["conversation_id"]))

    async with tenant_session(tenant_id) as conn, conn.transaction():
        row = await conn.fetchrow(
            """select cv.id, cv.assigned_to, cv.team_id,
                      ct.id as contact_id, ct.owner_id as contact_owner, ct.locale, ct.country,
                      t.sales_settings,
                      -- came from a Click-to-WhatsApp ad: the referral is on the
                      -- message that started the conversation (migration 0007)
                      exists (select 1 from messages m
                               where m.conversation_id = cv.id
                                 and m.referral is not null) as from_ad
               from conversations cv
               join contacts ct on ct.id = cv.contact_id
               join tenants t on t.id = cv.tenant_id
               where cv.id = $1""",
            conversation_id,
        )
        if row is None or row["assigned_to"] is not None:
            return

        settings = SalesSettings.model_validate(row["sales_settings"] or {})
        team_id = row["team_id"] or route_to_team(
            settings.routing_rules,
            language=row["locale"],
            country=row["country"],
            from_ad=row["from_ad"],
            default_team_id=settings.default_team_id,
        )

        chosen = await _keep_their_own(conn, tenant_id, row["contact_owner"])
        if chosen is None and team_id is not None:
            chosen = await _next_in_rotation(conn, tenant_id, team_id, language=row["locale"])

        if chosen is None:
            # Not a failure: the team is away or full. Try again shortly — a rep
            # back from lunch is as common as a team opening.
            if team_id is not None and row["team_id"] is None:
                await conn.execute(
                    "update conversations set team_id = $2 where id = $1", conversation_id, team_id
                )
            now = datetime.now(UTC)
            await emit(
                conn,
                "conversation.assign_requested",
                {"conversation_id": str(conversation_id)},
                tenant_id=tenant_id,
                dedupe_key=f"assign-retry:{conversation_id}:{int(now.timestamp()) // 900}",
                run_after=now + timedelta(minutes=15),
                priority=8,
            )
            log.info("assignment_deferred", conversation_id=str(conversation_id))
            return

        assigned = await conn.fetchrow(_ASSIGN, conversation_id, chosen)
        if assigned is None:  # someone else took it between the read and the write
            return
        await conn.execute(
            "update memberships set last_assigned_at = now() where tenant_id = $1 and user_id = $2",
            tenant_id,
            chosen,
        )
        await conn.execute(
            "update contacts set owner_id = coalesce(owner_id, $2) where id = $1",
            assigned["contact_id"],
            chosen,
        )
        name = await conn.fetchval("select full_name from profiles where id = $1", chosen)
        await _event_line(
            conn, tenant_id, conversation_id, "assigned", f"Assigned to {name or 'a colleague'}"
        )
        await notify(
            conn,
            tenant_id=tenant_id,
            user_id=chosen,
            kind="assigned",
            title="A customer is waiting for you",
            entity={"type": "conversation", "id": str(conversation_id)},
            dedupe_key=f"assigned:{conversation_id}:{chosen}",
        )


@handler("conversation.sla_check")
async def on_sla_check(event: Event) -> None:
    """Warn before the target, then once after it. Silent if the customer was answered.

    Scheduled by the message that started the wait rather than by a sweep: exact,
    and one queue row instead of a job a minute per tenant. The screen never
    depends on it — the inbox computes the state from sla_due_at when it is read.
    """
    if event.tenant_id is None:
        raise ValueError("conversation.sla_check requires a tenant")
    tenant_id = event.tenant_id
    conversation_id = UUID(str(event.payload["conversation_id"]))
    level = str(event.payload.get("level") or "due_soon")
    waiting_since = str(event.payload.get("waiting_since") or "")

    async with tenant_session(tenant_id) as conn, conn.transaction():
        row = await conn.fetchrow(
            """select cv.waiting_since, cv.sla_due_at, cv.assigned_to, cv.team_id, ct.full_name
               from conversations cv join contacts ct on ct.id = cv.contact_id
               where cv.id = $1""",
            conversation_id,
        )
        # Answered, or this check belongs to an older wait: nothing to say.
        if row is None or row["waiting_since"] is None:
            return
        if waiting_since and row["waiting_since"].isoformat() != waiting_since:
            return

        started = row["waiting_since"].isoformat()
        managers = [
            r["user_id"] for r in await conn.fetch(_TEAM_MANAGERS, tenant_id, row["team_id"])
        ]
        if row["assigned_to"] is None:
            kind, recipients = "unassigned_waiting", managers
        elif level == "missed":
            kind, recipients = "waiting_missed", [row["assigned_to"], *managers]
        else:
            kind, recipients = "waiting_due_soon", [row["assigned_to"]]

        title = f"{row['full_name'] or 'A customer'} is waiting"
        for user_id in dict.fromkeys(recipients):
            await notify(
                conn,
                tenant_id=tenant_id,
                user_id=user_id,
                kind=kind,
                title=title,
                entity={"type": "conversation", "id": str(conversation_id)},
                dedupe_key=f"{kind}:{conversation_id}:{started}:{user_id}",
            )

        if level == "due_soon":
            await emit(
                conn,
                "conversation.sla_check",
                {
                    "conversation_id": str(conversation_id),
                    "level": "missed",
                    "waiting_since": started,
                },
                tenant_id=tenant_id,
                dedupe_key=f"sla:{conversation_id}:{started}:missed",
                run_after=row["sla_due_at"],
                priority=8,
            )


@handler("notification.requested")
async def on_notification_requested(event: Event) -> None:
    """Turn an intent to notify into rows for the people who can act on it."""
    if event.tenant_id is None:
        raise ValueError("notification.requested requires a tenant")
    tenant_id = event.tenant_id
    payload = event.payload
    kind = str(payload.get("kind") or "message_received")
    if kind not in _NOTIFICATIONS:
        log.warning("notification_kind_unknown", kind=kind)
        return
    title, body = _NOTIFICATIONS[kind]

    async with tenant_session(tenant_id) as conn, conn.transaction():
        if kind == "message_received":
            conversation_id = UUID(str(payload["conversation_id"]))
            row = await conn.fetchrow(
                """select cv.assigned_to, cv.team_id, ct.full_name
                   from conversations cv join contacts ct on ct.id = cv.contact_id
                   where cv.id = $1""",
                conversation_id,
            )
            if row is None:
                return
            recipients: list[UUID] = (
                [row["assigned_to"]]
                if row["assigned_to"]
                # Nobody owns it yet, so it is the managers' problem, not nobody's.
                else [
                    r["user_id"]
                    for r in await conn.fetch(_TEAM_MANAGERS, tenant_id, row["team_id"])
                ]
            )
            title = f"{row['full_name'] or 'A customer'} sent a message"
            entity = {"type": "conversation", "id": str(conversation_id)}
            dedupe = f"message:{payload.get('message_id')}"
        else:
            recipients = [r["user_id"] for r in await conn.fetch(_ADMINS, tenant_id)]
            entity = {
                key: str(value)
                for key, value in payload.items()
                if key != "kind" and value is not None
            }
            dedupe = f"{kind}:{payload.get('template_id') or payload.get('channel_id')}"

        for user_id in dict.fromkeys(recipients):  # ordered, and each person once
            await notify(
                conn,
                tenant_id=tenant_id,
                user_id=user_id,
                kind=kind,
                title=title,
                body=body,
                entity=entity,
                dedupe_key=f"{dedupe}:{user_id}",
            )


async def _keep_their_own(
    conn: asyncpg.Connection, tenant_id: UUID, contact_owner: UUID | None
) -> UUID | None:
    """The customer's own salesperson keeps them, if they are taking chats."""
    if contact_owner is None:
        return None
    available = await conn.fetchval(
        """select user_id from memberships
           where tenant_id = $1 and user_id = $2 and accepting_chats""",
        tenant_id,
        contact_owner,
    )
    if available is None:
        return None
    return UUID(str(await conn.fetchval(_CLAIM_MEMBER, tenant_id, contact_owner) or available))


async def _next_in_rotation(
    conn: asyncpg.Connection, tenant_id: UUID, team_id: UUID, *, language: str | None
) -> UUID | None:
    """Pick, then lock. Locking every candidate first would make a second
    assignment happening right now find nobody at all."""
    candidates = [
        Candidate(
            user_id=c["user_id"],
            languages=tuple(c["languages"] or ()),
            accepting_chats=c["accepting_chats"],
            open_conversations=c["open_conversations"],
            max_open_conversations=c["max_open_conversations"],
            last_assigned_at=c["last_assigned_at"],
        )
        for c in await conn.fetch(_CANDIDATES, tenant_id, team_id)
    ]
    while candidates:
        chosen = choose(candidates, language=language)
        if chosen is None:
            return None
        if await conn.fetchval(_CLAIM_MEMBER, tenant_id, chosen) is not None:
            return chosen
        # Someone else is assigning to them this instant; take the next one.
        candidates = [c for c in candidates if c.user_id != chosen]
    return None
