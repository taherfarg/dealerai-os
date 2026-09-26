"""A grey line in a thread.

A conversation's history belongs in the conversation, not in an audit log
nobody opens: assigned, closed, reopened, reassigned, moved to another stage.
One function, because three copies of the same insert is how the same event
ends up looking different depending on which code path wrote it.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID


async def event_line(
    conn: Any, tenant_id: UUID, conversation_id: UUID, kind: str, text: str, **extra: str
) -> None:
    """`kind` is what happened; `text` is what the thread shows."""
    await conn.execute(
        """insert into messages (tenant_id, conversation_id, kind, type, direction, sender,
                                 origin, event)
           values ($1, $2, 'event', 'text', 'out', 'system', 'system', $3)""",
        tenant_id,
        conversation_id,
        {"type": kind, "text": text, **extra},
    )
