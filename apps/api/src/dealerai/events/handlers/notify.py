"""Telling somebody something happened, in one place.

The bell, the tab title and — from S7 — web push all read the same rows, so
where a notification takes you is decided here rather than at each call site.
"""

from __future__ import annotations

from uuid import UUID

import asyncpg

#: entity type → where clicking the notification goes, relative to the tenant.
_HREFS: dict[str, str] = {
    "conversation": "/inbox/{id}",
    "contact": "/customers/{id}",
    "lead": "/pipeline?lead={id}",
    "task": "/tasks",
    "brief": "/dashboard",
}


def href_for(entity: dict[str, str]) -> str | None:
    template = _HREFS.get(str(entity.get("type") or ""))
    return template.format(id=entity["id"]) if template and entity.get("id") else None


async def notify(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    user_id: UUID,
    kind: str,
    title: str,
    body: str | None = None,
    entity: dict[str, str] | None = None,
    dedupe_key: str | None = None,
) -> None:
    """One row, once. `dedupe_key` is what makes "once" true across retries."""
    entity = entity or {}
    await conn.execute(
        """insert into notifications (tenant_id, user_id, kind, title, body, href, entity,
                                      dedupe_key)
           values ($1, $2, $3, $4, $5, $6, $7, $8)
           on conflict do nothing""",
        tenant_id,
        user_id,
        kind,
        title,
        body,
        href_for(entity),
        entity,
        dedupe_key,
    )
