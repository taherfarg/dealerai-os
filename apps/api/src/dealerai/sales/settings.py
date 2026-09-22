"""The validated shape of tenants.sales_settings.

The column is jsonb and is read whole, never filtered on (docs/03-database-schema.md § 3).
This is where it becomes typed, once, at the edge — and `extra="ignore"` is deliberate:
a newer deploy writing a key this version has never seen must not break it.
"""

from __future__ import annotations

from datetime import time
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
#: Indexed by datetime.weekday(), so Monday is first.
WEEKDAYS: tuple[Weekday, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


class OpenHours(BaseModel):
    model_config = ConfigDict(extra="ignore")

    open: time
    close: time

    @field_validator("close")
    @classmethod
    def _after_open(cls, value: time, info: ValidationInfo) -> time:
        opens = info.data.get("open")
        if opens is not None and value <= opens:
            # A day that closes before it opens would make every reply late forever.
            raise ValueError("close must be after open")
        return value


class RoutingRule(BaseModel):
    """First match wins (docs/sales/05-workflows.md § 5)."""

    model_config = ConfigDict(extra="ignore")

    #: An empty list matches every value; a non-empty one must contain the conversation's.
    languages: list[str] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)
    #: True to match only conversations that started from a Click-to-WhatsApp ad.
    from_ad: bool | None = None
    team_id: UUID


class SalesSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    #: Minutes a waiting customer should wait, counted in business hours.
    first_response_target_min: int = Field(default=5, ge=1, le=24 * 60)
    #: Whether a salesperson sees their teams' unassigned queue. RLS reads the
    #: same key (app.pool_visible, migration 0006), so the name must not drift.
    unassigned_visible_to_sales: bool = True
    default_team_id: UUID | None = None
    #: A day missing from the map is a closed day; an empty map means always open.
    business_hours: dict[Weekday, OpenHours] = Field(default_factory=dict)
    routing_rules: list[RoutingRule] = Field(default_factory=list)
    #: Whether the AI drafts replies in the inbox at all. A dealership that
    #: switches this off keeps everything else; the draft handler checks it
    #: before spending anything. `db/queries/copilot.py` reads the same key in
    #: SQL, so the name must not drift.
    drafts_enabled: bool = True
    #: Days to wait before each AI follow-up on one lead, measured from the one
    #: before it. The list *is* the schedule: three entries means three
    #: follow-ups and then silence, after which the `silent` signal carries the
    #: lead to cold on its own — which is the correct ending
    #: (docs/sales/04-ai-copilot.md § 6).
    follow_up_cadence_days: list[int] = Field(default_factory=lambda: [2, 5, 14])
    #: Signal → points, overriding sales/scoring.py's defaults. No UI in Phase 1
    #: (docs/sales/04-ai-copilot.md § 5); a dealership that wants different
    #: arithmetic gets it by hand, and the reasons on screen stay honest either way.
    scoring_weights: dict[str, int] = Field(default_factory=dict)
