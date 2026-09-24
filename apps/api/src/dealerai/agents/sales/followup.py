"""A genuine reason to write again, or nothing.

The interesting output is `genuine_reason: false`, and the prompt spends most
of its length making that a comfortable answer. Every dealership already has an
automated follow-up system and every customer has muted it; the difference is
being allowed to produce nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from ...ai.gateway import SystemLayers
from ...ai.models import TaskKind
from ...ai.prompts import load
from ...core.security import AuthedUser
from ...deps import TenantContext
from ...orchestrator.toolloop import converse

#: Two lookups is plenty: this is one car and one customer, already named.
MAX_TOOL_CALLS = 2

TOOLS = ["get_vehicle", "search_inventory"]

#: What the trigger means, in the words the agent is asked to judge.
WHY: dict[str, str] = {
    "no_reply_48h": (
        "They have not replied for two days. Look at what was last said: is there "
        "anything they still do not know, or were you simply waiting?"
    ),
    "price_drop": "The price of a car they asked about has come down.",
    "similar_arrival": "A car matching what they said they wanted has arrived.",
}


class Written(BaseModel):
    genuine_reason: bool
    #: Required, and "" when there is no genuine reason. Schema decoding
    #: guarantees required fields and nothing else: the copilot's optional
    #: `reply` came back missing one draft in seven.
    reason: str
    draft: str
    language: Literal["ar", "en", "fr"] = "en"


@dataclass(frozen=True, slots=True)
class Considered:
    written: Written | None
    cost_usd: float


async def consider(*, tenant_id: UUID, run_id: UUID, trigger: str, context: str) -> Considered:
    """`context` is the lead, the car and the conversation tail, already built."""
    ctx = TenantContext(
        tenant_id=tenant_id,
        user=AuthedUser(id=run_id, email=None, claims={}),
        role="sales",
    )
    answer = await converse(
        TaskKind.SALES_REPLY,
        ctx=ctx,
        system=SystemLayers(role=load("_rules") + "\n\n" + load("followup")),
        prompt=(
            f"## Why you are looking at this\n{WHY.get(trigger, trigger)}\n\n"
            f"{context}\n\n"
            "Is there a genuine reason to write to them again?"
        ),
        tools=TOOLS,
        output_schema=Written,
        run_id=run_id,
        max_turns=MAX_TOOL_CALLS,
        trace_name=f"followup:{trigger}",
    )
    written = answer.parsed if isinstance(answer.parsed, Written) else None
    if written is not None and written.genuine_reason and not (written.reason and written.draft):
        # "Yes" with nothing to show for it is a no. The salesperson would get
        # a task whose title is empty and a draft that says nothing.
        written = Written(genuine_reason=False, reason="", draft="")
    return Considered(written=written, cost_usd=answer.cost_usd)
