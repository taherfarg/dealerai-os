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


async def most_asked(conn: Any, since: datetime, until: datetime) -> list[tuple[str, int]]:
    return [(row["car"], row["times"]) for row in await conn.fetch(q.MOST_ASKED, since, until)]


def render_facts(
    day: date,
    facts: dict[str, Any],
    team: list[dict[str, Any]],
    cars: list[tuple[str, int]],
) -> str:
    """The brief's facts as the headline's model reads them, and as
    guards/facts.py checks the headline against — so every number it may use
    is here in the form it may use it: minutes rather than seconds, a share
    already worked out. Salespeople are named; no customer is."""

    def minutes(seconds: int | None) -> str:
        return "nothing answered" if seconds is None else f"{round(seconds / 60)} min"

    replies = facts["replies_inbox"] + facts["replies_phone"]
    lines = [
        f"## Yesterday, {day:%A} {day.day} {day:%B}",
        f"- new conversations: {facts['new_conversations']}",
        f"- first reply, median: {minutes(facts['median_first_response_seconds'])}"
        f" (the target is {minutes(facts['first_response_target_seconds'])})",
        f"- replies that missed the target: {facts['missed_targets']}",
        f"- new leads: {facts['new_leads']}; won: {facts['won']}; lost: {facts['lost']}",
    ]
    if replies:
        lines.append(
            f"- replies from the inbox: {facts['replies_inbox']} of {replies}"
            f" ({round(100 * facts['replies_inbox'] / replies)}%);"
            f" typed on the phone: {facts['replies_phone']}"
        )
    if cars:
        lines.append(
            "- cars asked about most: " + ", ".join(f"{car} ({times})" for car, times in cars)
        )
    lines += [
        "",
        "## This morning",
        f"- customers waiting: {facts['waiting_now']};"
        f" past the target: {facts['waiting_past_target']}",
        f"- hot leads with no next step: {facts['hot_without_next_step']}",
        f"- open tasks past their due time: {facts['overdue_tasks']}",
    ]
    if team:
        lines += ["", "## By salesperson"]
        lines += [
            f"- {rep['name'] or 'unnamed'}: first reply median"
            f" {minutes(rep['median_first_response_seconds'])}, missed {rep['missed_targets']},"
            f" tasks past due {rep['overdue_tasks']}, won this month {rep['won_this_month']}"
            for rep in team
        ]
    return "\n".join(lines)
