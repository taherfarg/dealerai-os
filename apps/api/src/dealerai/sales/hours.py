"""Business-hours arithmetic for response targets.

A customer who writes at 23:30 is not late at 23:35. Targets count minutes the
team is actually open, in the tenant's own timezone — which is why this takes a
`tz` rather than reading one from the process.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .settings import WEEKDAYS, OpenHours, SalesSettings

#: How far ahead to look for an open minute before giving up. A tenant whose
#: hours never open still gets a due time rather than none at all.
_HORIZON_DAYS = 14


def _hours_for(moment: datetime, settings: SalesSettings) -> OpenHours | None:
    return settings.business_hours.get(WEEKDAYS[moment.weekday()])


def _next_midnight(moment: datetime) -> datetime:
    return (moment + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


def is_open(moment: datetime, *, settings: SalesSettings, tz: ZoneInfo) -> bool:
    """Is the team open at this instant? A tenant with no hours is always open."""
    if not settings.business_hours:
        return True
    local = moment.astimezone(tz)
    hours = _hours_for(local, settings)
    return hours is not None and hours.open <= local.time() < hours.close


def due_at(
    waiting_since: datetime,
    *,
    settings: SalesSettings,
    tz: ZoneInfo,
    target_minutes: int | None = None,
) -> datetime:
    """When a reply to a message received at `waiting_since` becomes late."""
    remaining = timedelta(minutes=target_minutes or settings.first_response_target_min)
    if not settings.business_hours:
        return waiting_since + remaining

    cursor = waiting_since.astimezone(tz)
    for _ in range(_HORIZON_DAYS):
        hours = _hours_for(cursor, settings)
        if hours is None:  # a closed day: start at the next one
            cursor = _next_midnight(cursor)
            continue

        opens = cursor.replace(
            hour=hours.open.hour, minute=hours.open.minute, second=0, microsecond=0
        )
        closes = cursor.replace(
            hour=hours.close.hour, minute=hours.close.minute, second=0, microsecond=0
        )
        if cursor < opens:
            cursor = opens
        if cursor >= closes:  # after closing: try tomorrow
            cursor = _next_midnight(cursor)
            continue

        left_today = closes - cursor
        if remaining <= left_today:
            return (cursor + remaining).astimezone(waiting_since.tzinfo)
        remaining -= left_today
        cursor = _next_midnight(closes)

    # Hours that never open: fall back to the clock rather than returning nothing.
    return waiting_since + remaining
