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

from pydantic import BaseModel

from ..db.queries import dashboard as q
from .hours import open_seconds
from .settings import SalesSettings

#: How many things the brief puts in front of a manager.
BRIEF_ITEMS = 5


class Headline(BaseModel):
    """The brief's one line, in both UI languages. Both required: schema
    decoding guarantees required fields and nothing else."""

    en: str
    ar: str


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


async def facts(
    conn: Any,
    since: datetime,
    until: datetime,
    now: datetime,
    waits: list[Wait],
    settings: SalesSettings,
) -> dict[str, Any]:
    row = await conn.fetchrow(q.FACTS, since, until, now)
    return {
        **dict(row),
        "median_first_response_seconds": median_of(waits),
        "first_response_target_seconds": settings.first_response_target_min * 60,
    }


async def team(
    conn: Any,
    tenant_id: UUID,
    since: datetime,
    until: datetime,
    now: datetime,
    waits: list[Wait],
    month_from: datetime,
) -> list[dict[str, Any]]:
    rows = await conn.fetch(q.TEAM, tenant_id, since, until, now, month_from)
    return [
        {
            **dict(row),
            "median_first_response_seconds": median_of(
                [wait for wait in waits if wait.assigned_to == row["id"]]
            ),
        }
        for row in rows
    ]


def rank(
    waits: list[dict[str, Any]],
    hot: list[dict[str, Any]],
    overdue: list[dict[str, Any]],
    limit: int = BRIEF_ITEMS,
) -> list[dict[str, Any]]:
    """Two of each kind first, so a busy inbox cannot hide a hot lead nobody is
    working; then the rest, the most urgent kind first."""
    first = [*waits[:2], *hot[:2], *overdue[:1]]
    rest = [*waits[2:], *hot[2:], *overdue[1:]]
    return (first + rest)[:limit]


async def attention(conn: Any, now: datetime) -> list[dict[str, Any]]:
    """What needs somebody now, ranked — the brief's items, live rather than
    stored, so an item somebody already handled is gone when they look."""
    waits = [
        {"kind": "waiting", **dict(row)}
        for row in await conn.fetch(q.ATTENTION_WAITS, now, BRIEF_ITEMS)
    ]
    hot = [
        {"kind": "hot_lead", **dict(row)} for row in await conn.fetch(q.ATTENTION_HOT, BRIEF_ITEMS)
    ]
    overdue = [
        {"kind": "overdue_tasks", **dict(row)}
        for row in await conn.fetch(q.ATTENTION_OVERDUE, now, BRIEF_ITEMS)
    ]
    return rank(waits, hot, overdue)
