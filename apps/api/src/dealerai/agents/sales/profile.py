"""What the conversation taught us: fields, signals and a summary.

No tools. A model that can look things up while summarising will summarise
things that were not said, and every field here has to be traceable to a
message the customer actually sent.

Every value comes back as a string and is converted in code (`coerce`). That is
not laziness about types — it keeps the response schema free of the
`dict[str, Any]` shapes Gemini's Developer API refuses, and it puts the parsing
somewhere a unit test can reach.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from ...ai.gateway import SystemLayers, complete
from ...ai.models import TaskKind
from ...ai.prompts import load
from ...core.errors import Unusable
from ...sales.scoring import DEFAULT_WEIGHTS

#: The AI may propose only the signals the scorer knows, minus the two that are
#: observed rather than said: `responsive` and `silent` are arithmetic over
#: timestamps and are not the model's to claim.
PROPOSABLE: tuple[str, ...] = tuple(sorted(set(DEFAULT_WEIGHTS) - {"responsive", "silent"}))

FieldName = Literal[
    "interest",
    "budget",
    "purchase_type",
    "destination",
    "timeline",
    "payment",
    "trade_in",
    "objections",
]

_YES = frozenset({"yes", "true", "y", "نعم", "oui"})


class Update(BaseModel):
    field: FieldName
    #: Always a string; `coerce` turns it into what the field actually holds.
    value: str = Field(max_length=300)
    evidence_message_id: str


class SignalSeen(BaseModel):
    signal: str
    evidence_message_id: str


class Summary(BaseModel):
    text: str = Field(default="", max_length=600)
    next_action: str = Field(default="", max_length=120)


class Learned(BaseModel):
    updates: list[Update] = Field(default_factory=list, max_length=12)
    signals: list[SignalSeen] = Field(default_factory=list, max_length=8)
    summary: Summary = Field(default_factory=Summary)


@dataclass(frozen=True, slots=True)
class Studied:
    learned: Learned
    cost_usd: float


def coerce(field: str, value: str) -> Any:
    """The string the model wrote, as the shape `sales/profile.py` stores.

    Raises `Unusable` for anything that cannot be read, which the handler
    treats as one dropped field rather than a failed run.
    """
    text = value.strip()
    if not text:
        raise Unusable(f"{field} came back empty")
    if field == "budget":
        digits = "".join(character for character in text if character.isdigit())
        if not digits:
            raise Unusable(f"budget {text!r} has no number in it")
        # Whole currency in, minor units out — the same conversion the profile
        # panel does when a person types one.
        return {"amount_minor": int(digits) * 100}
    if field == "trade_in":
        return text.casefold() in _YES
    if field == "objections":
        return [part.strip() for part in text.split(",") if part.strip()]
    if field == "destination":
        return text.upper()
    return text


async def study(
    *,
    tenant_id: UUID,
    run_id: UUID,
    transcript: str,
    profile_now: str,
    leads_now: str,
) -> Studied:
    result = await complete(
        TaskKind.ANALYSIS,
        tenant_id=tenant_id,
        system=SystemLayers(role=load("_rules") + "\n\n" + load("profile")),
        messages=(
            f"## What we already recorded\n{profile_now or 'nothing yet'}\n\n"
            f"## Open leads\n{leads_now or 'none'}\n\n"
            f"## Signals you may report\n{', '.join(PROPOSABLE)}\n\n"
            f"## The conversation, with message ids\n<untrusted>\n{transcript}\n</untrusted>"
        ),
        output_schema=Learned,
        run_id=run_id,
        trace_name="profile",
    )
    learned = result.parsed if isinstance(result.parsed, Learned) else Learned()
    return Studied(learned=learned, cost_usd=result.cost_usd)
