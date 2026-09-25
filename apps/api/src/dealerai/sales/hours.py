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


def next_opening(moment: datetime, *, settings: SalesSettings, tz: ZoneInfo) -> datetime:
    """When the showroom is next open, or `moment` itself if it is open now.

    A follow-up that lands at 02:00 is a follow-up that gets the number
    blocked, and "send it tomorrow" has to mean a real instant the queue can
    hold. A tenant with no hours is always open, like everywhere else here.
    """
    if not settings.business_hours:
        return moment
    cursor = moment.astimezone(tz)
    for _ in range(_HORIZON_DAYS):
        hours = _hours_for(cursor, settings)
        if hours is None:  # a closed day
            cursor = _next_midnight(cursor)
            continue
        opens = cursor.replace(
            hour=hours.open.hour, minute=hours.open.minute, second=0, microsecond=0
        )
        closes = cursor.replace(
            hour=hours.close.hour, minute=hours.close.minute, second=0, microsecond=0
        )
        if cursor < opens:
            return opens.astimezone(moment.tzinfo)
        if cursor < closes:
            return moment  # open right now
        cursor = _next_midnight(cursor)
    # Hours that never open: send it rather than holding it for ever.
    return moment


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


def open_seconds(start: datetime, end: datetime, *, settings: SalesSettings, tz: ZoneInfo) -> int:
    """How much of [start, end) the team was open: the wait a response target
    counts. A customer who wrote at 23:30 and was answered at 09:02 waited two
    minutes of the team's time, not nine and a half hours."""
    if end <= start:
        return 0
    if not settings.business_hours:
        return int((end - start).total_seconds())
    total = timedelta()
    cursor = start.astimezone(tz)
    stop = end.astimezone(tz)
    while cursor < stop:
        hours = _hours_for(cursor, settings)
        if hours is not None:
            opens = cursor.replace(
                hour=hours.open.hour, minute=hours.open.minute, second=0, microsecond=0
            )
            closes = cursor.replace(
                hour=hours.close.hour, minute=hours.close.minute, second=0, microsecond=0
            )
            counted_from, counted_to = max(cursor, opens), min(stop, closes)
            if counted_to > counted_from:
                total += counted_to - counted_from
        cursor = _next_midnight(cursor)
    return int(total.total_seconds())
