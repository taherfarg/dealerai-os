"""Postgres NOTIFY to open SSE streams, one LISTEN connection per process.

The event is a nudge, never data: it carries ids, and the browser refetches over
REST. That is what makes a missed event cost a request instead of showing a
stale screen — and what keeps customer messages out of Postgres's notification
queue, which is global to the database.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import structlog

log = structlog.get_logger()

#: How many events a single browser tab may fall behind before the oldest is
#: dropped. A tab that stopped reading is a tab that refetches when it returns.
MAX_QUEUED = 100

#: Longest wait between attempts to get the listener back.
MAX_BACKOFF_SECONDS = 30.0


#: eq=False keeps identity semantics: two tabs open for the same person are two
#: different streams, and the hub holds them in a set.
@dataclass(eq=False)
class Subscriber:
    tenant_id: UUID
    user_id: UUID
    scope: str
    #: Owner ids this person may see, from app.visible_owner_ids(). Empty with
    #: scope `all` means "no owner filter", which is why scope is checked first.
    visible_owner_ids: set[UUID]
    team_ids: set[UUID]
    queue: asyncio.Queue[str] = field(default_factory=asyncio.Queue)
    dropped: int = 0

    def may_see(self, event: dict[str, Any]) -> bool:
        if str(event.get("tenant_id")) != str(self.tenant_id):
            return False
        for_user = event.get("user_id")
        if for_user:  # a notification belongs to exactly one person
            return str(for_user) == str(self.user_id)
        if self.scope == "all":
            return True

        assignee = event.get("assigned_to")
        if assignee and str(assignee) == str(self.user_id):
            return True  # covering for a colleague
        owner = event.get("owner_id")
        if owner and UUID(str(owner)) in self.visible_owner_ids:
            return True
        # The team's unassigned queue — the same rule app.pool_visible() applies.
        team = event.get("team_id")
        return not owner and not assignee and bool(team) and UUID(str(team)) in self.team_ids


class Hub:
    """Every open stream on this process."""

    def __init__(self, max_queued: int = MAX_QUEUED) -> None:
        self._subscribers: set[Subscriber] = set()
        self._max_queued = max_queued

    def subscribe(self, subscriber: Subscriber) -> Subscriber:
        self._subscribers.add(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: Subscriber) -> None:
        self._subscribers.discard(subscriber)

    @property
    def open_streams(self) -> int:
        return len(self._subscribers)

    def publish(self, raw: str) -> None:
        """Called by the LISTEN callback.

        Never blocks and never raises: a slow tab loses events, not the process.
        """
        try:
            event = json.loads(raw)
        except ValueError:
            log.warning("realtime_payload_unreadable")
            return
        if not isinstance(event, dict):
            return
        for subscriber in self._subscribers:
            if not subscriber.may_see(event):
                continue
            if subscriber.queue.qsize() >= self._max_queued:
                with contextlib.suppress(asyncio.QueueEmpty):
                    subscriber.queue.get_nowait()
                subscriber.dropped += 1
            subscriber.queue.put_nowait(raw)


#: The process's hub. One per API process, as many streams as it has tabs.
hub = Hub()


async def listen(stop: asyncio.Event) -> None:
    """Hold one connection on LISTEN 'rt' for the life of the process.

    Reconnects with backoff: a lost listener means every screen stops moving,
    and they must start again without a deploy.
    """
    from .db import session  # here, because only db.session may take a connection

    delay = 1.0
    while not stop.is_set():
        try:
            async with session.listen_connection() as conn:

                def on_notify(*args: object) -> None:
                    hub.publish(str(args[-1]))

                await conn.add_listener("rt", on_notify)
                log.info("realtime_listening")
                delay = 1.0
                try:
                    await stop.wait()
                finally:
                    await conn.remove_listener("rt", on_notify)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("realtime_listener_lost", retry_in=delay)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=delay)
            delay = min(delay * 2, MAX_BACKOFF_SECONDS)
