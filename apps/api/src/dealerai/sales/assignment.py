"""Who takes a waiting conversation. Pure: candidates in, one id out.

The database part — locking the person we picked so two arrivals cannot pick the
same one — lives in the handler. The rule itself is here, where it can be read.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from .settings import RoutingRule


@dataclass(frozen=True, slots=True)
class Candidate:
    user_id: UUID
    languages: tuple[str, ...]
    accepting_chats: bool
    open_conversations: int
    max_open_conversations: int | None
    last_assigned_at: datetime | None


def _available(candidate: Candidate) -> bool:
    if not candidate.accepting_chats:
        return False
    limit = candidate.max_open_conversations
    return limit is None or candidate.open_conversations < limit


def choose(candidates: Iterable[Candidate], *, language: str | None) -> UUID | None:
    """The least recently assigned available person, preferring a shared language.

    Language first, then rotation: a French customer reaching an Arabic-only rep
    is a worse start than waiting one place longer in the queue. Nobody available
    returns None — the conversation stays in the team's queue and is tried again.
    """
    available = [c for c in candidates if _available(c)]
    if not available:
        return None
    speaks = [c for c in available if language and language in c.languages]
    pool = speaks or available
    # Never assigned sorts first: a new rep should not wait out a full rotation.
    epoch = datetime.min.replace(tzinfo=UTC)
    return min(pool, key=lambda c: c.last_assigned_at or epoch).user_id


def route_to_team(
    rules: Sequence[RoutingRule],
    *,
    language: str | None,
    country: str | None,
    from_ad: bool,
    default_team_id: UUID | None,
) -> UUID | None:
    """The first rule that matches, else the tenant's default team."""
    for rule in rules:
        if rule.languages and language not in rule.languages:
            continue
        if rule.countries and country not in rule.countries:
            continue
        if rule.from_ad is not None and rule.from_ad is not from_ad:
            continue
        return rule.team_id
    return default_team_id
