"""May we write to this customer again? Decided in code, before any model call.

Every dealership already has an automated follow-up system, and every customer
has muted it. What makes this one different is that most "no"s cost nothing:
the checks here run first, and only a lead that passes all of them is worth
asking a model whether there is anything to say
(docs/sales/04-ai-copilot.md § 6).

Pure on purpose — the rules are testable at the exact edge, which is where a
cadence is always wrong.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .hours import next_opening
from .settings import SalesSettings

#: Triggers tied to one car, where that car still being available is the point.
CAR_TRIGGERS = frozenset({"price_drop", "similar_arrival"})


@dataclass(frozen=True, slots=True)
class Eligibility:
    allowed: bool
    because: str = ""
    #: Set when it is only "not yet", so the caller can look again then rather
    #: than forgetting about this lead entirely.
    retry_at: datetime | None = None


def cap(settings: SalesSettings) -> int:
    """How many AI follow-ups one lead may ever get.

    The cadence list is the schedule, so its length is the cap: a dealership
    that shortens it to two gaps gets two follow-ups, which is what shortening
    it means.
    """
    return len(settings.follow_up_cadence_days)


def may_follow_up(
    lead: Any,
    *,
    trigger: str,
    now: datetime,
    settings: SalesSettings,
    tz: ZoneInfo,
) -> Eligibility:
    """Ordered cheapest and most final first, so a "no" is as cheap as possible.

    `lead` carries: `consent`, `ai_followups` (how many have been sent),
    `last_followup_at`, `vehicle_status`, `open_ai_task`.
    """
    if (lead["consent"] or {}).get("opted_out_at"):
        return Eligibility(False, "the customer asked not to be messaged")

    limit = cap(settings)
    if lead["ai_followups"] >= limit:
        # After the last one, the `silent` signal carries the lead to cold on
        # its own. That is the ending, not a fourth message.
        return Eligibility(False, f"{limit} AI follow-ups have already been sent")

    if trigger in CAR_TRIGGERS and lead["vehicle_status"] != "available":
        return Eligibility(False, "the car is no longer available")

    if lead["open_ai_task"]:
        return Eligibility(False, "there is already a follow-up waiting for them")

    due = _cadence_due(lead, settings)
    if due is not None and due > now:
        return Eligibility(False, "too soon by the cadence", retry_at=due)

    opening = next_opening(now, settings=settings, tz=tz)
    if opening > now:
        return Eligibility(False, "the showroom is closed", retry_at=opening)

    return Eligibility(True)


def _cadence_due(lead: Any, settings: SalesSettings) -> datetime | None:
    """When the next follow-up is allowed, or None when nothing is owed.

    The list is read as the wait before follow-up N, measured from the one
    before it — or, for the first, from the day the lead appeared. Every number
    in the default [2, 5, 14] is used that way: two days before the first, five
    before the second, a fortnight before the last.
    """
    last = lead["last_followup_at"] or lead["lead_created_at"]
    if last is None:
        return None
    # An empty list cannot reach here: `cap()` is its length, so a dealership
    # that emptied it has already been refused above.
    gaps = settings.follow_up_cadence_days
    sent = int(lead["ai_followups"])
    due: datetime = last + timedelta(days=gaps[min(sent, len(gaps) - 1)])
    return due
