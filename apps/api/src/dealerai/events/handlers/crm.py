"""The CRM's side of the queue: telling somebody a customer is theirs now, or
that a task of theirs fell due."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

import structlog

from ...db.session import tenant_session
from ..bus import Event, handler
from .notify import notify

log = structlog.get_logger()


@handler("contact.reassigned")
async def on_contact_reassigned(event: Event) -> None:
    """The person who just inherited a customer should not find out by accident.

    The handover itself already happened, in one transaction, in
    app.reassign_contact. This is the part that can safely be late.
    """
    if event.tenant_id is None:
        raise ValueError("contact.reassigned requires a tenant")
    contact_id = UUID(str(event.payload["contact_id"]))
    owner_id = UUID(str(event.payload["owner_id"]))
    actor_id = event.payload.get("actor_id")

    async with tenant_session(event.tenant_id) as conn:
        row = await conn.fetchrow(
            """select c.full_name,
                      (select p.full_name from profiles p where p.id = $2) as actor_name
                 from contacts c where c.id = $1""",
            contact_id,
            UUID(str(actor_id)) if actor_id else None,
        )
        if row is None:
            log.info("contact_reassigned_gone", contact_id=str(contact_id))
            return
        customer = row["full_name"] or "A customer"
        await notify(
            conn,
            tenant_id=event.tenant_id,
            user_id=owner_id,
            kind="contact_assigned",
            title=f"{customer} is yours now",
            body=f"Handed over by {row['actor_name']}" if row["actor_name"] else None,
            entity={"type": "contact", "id": str(contact_id)},
            # Handing the same customer to the same person twice is one piece of
            # news, however many times the button was pressed.
            dedupe_key=f"contact-assigned:{contact_id}:{owner_id}",
        )


@handler("task.due_check")
async def on_task_due(event: Event) -> None:
    """A task's due time came: tell its assignee — unless it was done,
    cancelled or moved since the trigger booked this (migration 0014)."""
    if event.tenant_id is None:
        raise ValueError("task.due_check requires a tenant")
    task_id = UUID(str(event.payload["task_id"]))
    booked = datetime.fromisoformat(str(event.payload["due_at"]))

    async with tenant_session(event.tenant_id) as conn:
        task = await conn.fetchrow(
            """select t.title, t.assignee_id, t.due_at, t.status, c.full_name
                 from tasks t left join contacts c on c.id = t.contact_id
                where t.id = $1""",
            task_id,
        )
        if task is None or task["status"] != "open" or task["due_at"] != booked:
            return
        await notify(
            conn,
            tenant_id=event.tenant_id,
            user_id=task["assignee_id"],
            kind="task_due",
            title=f"Due now: {task['title']}",
            body=task["full_name"],
            entity={"type": "task", "id": str(task_id)},
            # Re-opening a task after its time re-books the check; it is still
            # one piece of news.
            dedupe_key=f"task-due:{task_id}:{booked.isoformat()}",
        )
