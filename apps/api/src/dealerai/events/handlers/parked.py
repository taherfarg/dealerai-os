"""Event types that a later slice will handle.

The emitters are right to emit them now: a customer's message is what makes a
conversation need assigning and a person need notifying, and that is where the
intent belongs. What is missing is the consumer.

Until it exists, an unhandled type is retried five times and dead-lettered —
deliberately, because during a rolling deploy an old worker briefly sees types
it does not know (events/bus.py). For a type nobody has built yet, that turns
every customer message into red in the queue and in the logs.

Parking is how a type says "not built yet" instead. Taking one over is a
deletion here plus a real handler: `bus.register` refuses a second handler for
the same type, so a slice cannot quietly leave the placeholder behind.
"""

from __future__ import annotations

import structlog

from ..bus import Event, handler

log = structlog.get_logger()

#: event type -> the slice that will own it (docs/sales/09-implementation-plan.md,
#: docs/09-implementation-plan.md for the content milestones).
PARKED: dict[str, str] = {
    "vehicle.price_changed": "S7 follow-ups — a price drop worth a message",
    "vehicle.status_changed": "S7 follow-ups — the car a customer asked about moved",
    "vehicle.sold": "S7 follow-ups — stop offering a car that is gone",
    "vehicle.ready": "M4 publishing — a car with a full record can be marketed",
    "vehicle.photos_assessed": "M4 publishing — creative picks from ranked photos",
    "approval.requested": "M4 approvals — the reviewer's queue",
    "agent_run.finished": "M4 run history — what the agents did, for the dashboard",
}


def _park(event_type: str, owner: str) -> None:
    async def parked(event: Event) -> None:
        log.info(
            "event_parked",
            event_type=event.event_type,
            waiting_for=owner,
            payload=event.payload,
        )

    handler(event_type)(parked)


for _event_type, _owner in PARKED.items():
    _park(_event_type, _owner)
