"""When a piece of content may go out: the dealer's posting rules, on its clock.

T3.8 (docs/09-implementation-plan.md). The rules are the ones the autonomy gate
already reads — `tenants.autonomy_rules.publishing`, `max_posts_per_day` and
`quiet_hours` (docs/02-agent-architecture.md § the gate) — applied here to a
person choosing a slot, so a calendar a person filled cannot be one autopilot
would refuse. Pure: the routes count, this decides.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from .orchestrator.gate import in_quiet_hours

#: The most a calendar shows at once: a month and a bit.
MAX_DAYS = 62
#: Where a piece dropped on a day lands when it had no time of its own.
DEFAULT_TIME = time(10, 0)


@dataclass(frozen=True, slots=True)
class Rules:
    max_per_day: int | None = None
    quiet: tuple[time, time] | None = None


def rules_of(autonomy_rules: dict[str, Any] | None) -> Rules:
    """The publishing rules, or none where the dealer set none. A rule that
    cannot be read is no rule: the gate is where a bad rule fails closed."""
    publishing = (autonomy_rules or {}).get("publishing") or {}
    limit = publishing.get("max_posts_per_day")
    quiet = publishing.get("quiet_hours")
    try:
        hours = (time.fromisoformat(quiet[0]), time.fromisoformat(quiet[1])) if quiet else None
    except (TypeError, ValueError, IndexError):
        hours = None
    return Rules(max_per_day=limit if isinstance(limit, int) else None, quiet=hours)


def refusal(rules: Rules, *, day: date, at: time, already: int, now: datetime) -> str | None:
    """Why this slot cannot be taken, or None. `already` is how many other
    pieces go out that day; `now` is the dealer's own time, without a zone."""
    if datetime.combine(day, at) <= now:
        return f"{day:%A %d %B} {at:%H:%M} has already passed"
    if rules.quiet and in_quiet_hours(at, *rules.quiet):
        start, end = rules.quiet
        return f"{at:%H:%M} is inside quiet hours, {start:%H:%M}–{end:%H:%M}"
    if rules.max_per_day is not None and already >= rules.max_per_day:
        return (
            f"{day:%A %d %B} already has {already} of the {rules.max_per_day} posts a day allowed"
        )
    return None


def days(start: date, end: date) -> list[date]:
    """Every day from start to end, both included."""
    return [start + timedelta(days=n) for n in range((end - start).days + 1)]


def gaps(span: list[date], counts: dict[date, int], *, today: date) -> list[date]:
    """The days from today on with nothing going out: where the next piece goes.
    A day already gone is history, not a gap."""
    return [day for day in span if day >= today and not counts.get(day)]
