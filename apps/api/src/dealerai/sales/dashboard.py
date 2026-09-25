"""The arithmetic behind the manager's dashboard, the morning brief and My day.

In one place because a number shown on two screens is a number that can
disagree with itself: My day's median and the dashboard's are this module's.
SQL counts rows (db/queries/dashboard.py); this turns them into waits, medians,
windows and a ranked list. It has no visibility of its own — the caller's
session already decided which rows exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from statistics import median
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from ..db.queries import dashboard as q
from .hours import open_seconds
from .settings import SalesSettings


@dataclass(frozen=True, slots=True)
class Wait:
    """One first reply: who gave it, and how long the customer had waited, in business hours."""

    assigned_to: UUID | None
    seconds: int


def day_window(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """Midnight to midnight where the showroom is."""
    start = datetime.combine(day, time(0), tzinfo=tz)
    return start, datetime.combine(day + timedelta(days=1), time(0), tzinfo=tz)


def month_start(day: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(day.replace(day=1), time(0), tzinfo=tz)


async def answered(
    conn: Any, since: datetime, until: datetime, *, tz: ZoneInfo, settings: SalesSettings
) -> list[Wait]:
    """First replies given in the window, each wait counted in business hours
    because the target is."""
    return [
        Wait(
            row["assigned_to"],
            open_seconds(row["asked_at"], row["answered_at"], settings=settings, tz=tz),
        )
        for row in await conn.fetch(q.ANSWERED, since, until)
        if row["asked_at"] is not None  # we wrote first: nobody was waiting
    ]


def median_of(waits: list[Wait]) -> int | None:
    """Null rather than zero before anything was answered: a zero reads as instant."""
    return round(median(wait.seconds for wait in waits)) if waits else None
