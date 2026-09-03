"""Where a NEEDS_APPROVAL verdict goes.

The gate decides; this records the request and wakes whoever can answer it. Kept
separate from the routes because agents create approvals from inside the worker,
where there is no HTTP request to hang off.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import asyncpg

from ..events.bus import emit

#: Who may sign off on what. Money and prices need an admin; content and
#: customer replies do not, or the approval queue becomes the owner's full-time
#: job and Assisted mode stops being usable.
APPROVER_ROLE: dict[str, str] = {
    "publish_content": "marketer",
    "reply_comment": "sales",
    "send_message": "sales",
    "offer_discount": "admin",
    "adjust_budget": "admin",
    "launch_campaign": "admin",
    "price_change": "admin",
}
#: An approval kind nobody classified needs the highest role, not the lowest.
DEFAULT_APPROVER_ROLE = "admin"

DEFAULT_TTL_HOURS = 72


def approver_role(kind: str) -> str:
    return APPROVER_ROLE.get(kind, DEFAULT_APPROVER_ROLE)


async def request_approval(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    kind: str,
    summary: str,
    payload: dict[str, Any] | None = None,
    run_id: UUID | None = None,
    task_id: UUID | None = None,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    ttl_hours: int = DEFAULT_TTL_HOURS,
) -> UUID:
    """Record an approval request and emit `approval.requested`.

    Takes the caller's connection so the request and whatever produced it commit
    together — the same reason emit() does. An approval for a draft that rolled
    back is a prompt about nothing.
    """
    expires_at = datetime.now(UTC) + timedelta(hours=ttl_hours)
    approval_id: UUID = await conn.fetchval(
        """insert into approvals
             (tenant_id, run_id, task_id, kind, entity_type, entity_id,
              summary, payload, expires_at)
           values ($1,$2,$3,$4,$5,$6,$7,$8,$9)
           returning id""",
        tenant_id,
        run_id,
        task_id,
        kind,
        entity_type,
        entity_id,
        summary,
        payload or {},
        expires_at,
    )
    await emit(
        conn,
        "approval.requested",
        {"approval_id": str(approval_id), "kind": kind, "summary": summary},
        tenant_id=tenant_id,
        dedupe_key=f"approval:{approval_id}",
    )
    return approval_id
