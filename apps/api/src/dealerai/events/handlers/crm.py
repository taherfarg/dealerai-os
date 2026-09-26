"""The CRM's side of the queue: telling somebody a customer is theirs now."""

from __future__ import annotations

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
