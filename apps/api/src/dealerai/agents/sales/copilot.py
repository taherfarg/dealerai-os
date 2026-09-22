"""The draft. Four prompt layers, four tool calls, one schema.

The layer order is the cache order from DealerAI OS 01 § 5 and it is not
cosmetic: Gemini caches on a repeated prefix, so the role and tenant layers
must be byte-identical between calls. A timestamp in the tenant layer does not
merely move a breakpoint, it destroys the prefix — and the draft that was going
to cost half a cent costs three times that, every time, for every tenant.

The tool list is three, not the four in docs/sales/04-ai-copilot.md § 2. The
customer 360 is already in the context layer — sales/grounding.py puts it there
— and a tool that re-reads what the prompt already contains is a turn of
latency whose only possible contribution is disagreeing with it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

import structlog
from pydantic import BaseModel, Field

from ...ai.gateway import SystemLayers
from ...ai.models import TaskKind
from ...ai.prompts import load
from ...core.security import AuthedUser
from ...deps import TenantContext
from ...orchestrator.toolloop import converse
from ...sales.grounding import Ground, context_layer
from .intent import Read

log = structlog.get_logger()

#: docs/sales/04-ai-copilot.md § 3. Four, because a model on its fifth lookup is
#: lost rather than thorough, and a customer is waiting.
MAX_TOOL_CALLS = 4

#: Fixed in Python, not in the prompt. Least privilege by construction: the
#: copilot cannot change a price or send a message because it has no tool that
#: does, which is a code-level constraint rather than a sentence a sufficiently
#: confused model can talk itself past.
TOOLS = ["search_inventory", "get_vehicle", "search_knowledge"]


class ProposedAction(BaseModel):
    """Something for the salesperson to do in one click. Never done by the AI.

    Flat and explicitly typed rather than `params: dict[str, Any]`, which is
    what a free-form object looks like to Pydantic — and which Gemini's
    Developer API refuses outright: "additionalProperties is only supported in
    Gemini Enterprise Agent Platform mode". Every unit test stubbed the model
    and passed; the first live draft failed on it.

    Each field belongs to one `kind`. The chip is a proposal, and the endpoint
    behind it validates what it is given, so a nonsense `due_at` costs one
    422 with a sentence rather than a bad row.
    """

    kind: Literal["create_lead", "create_task", "update_profile"]
    #: What the chip says, in the UI language.
    label: str = Field(max_length=60)
    #: create_lead
    vehicle_id: str | None = None
    #: create_task
    title: str | None = Field(default=None, max_length=120)
    due_at: str | None = None
    #: update_profile
    field: str | None = None
    value: str | None = Field(default=None, max_length=200)


class Draft(BaseModel):
    """What the model is allowed to produce, and nothing else.

    `reply` and `template_name` are the two ways to answer. A closed window
    makes the second mandatory: the instruction says so, and the handler checks
    it afterwards anyway, because an instruction is not an enforcement.
    """

    reply: str | None = Field(default=None, max_length=1200)
    template_name: str | None = None
    template_variables: list[str] = Field(default_factory=list, max_length=20)
    language: Literal["ar", "en", "fr"]
    used_vehicle_ids: list[str] = Field(default_factory=list, max_length=6)
    used_chunk_ids: list[int] = Field(default_factory=list, max_length=8)
    actions: list[ProposedAction] = Field(default_factory=list, max_length=2)
    needs_human: str | None = Field(default=None, max_length=200)


@dataclass(frozen=True, slots=True)
class Drafted:
    draft: Draft | None
    cost_usd: float
    tool_calls: tuple[str, ...]


async def write(
    *,
    tenant_id: UUID,
    run_id: UUID,
    ground: Ground,
    read: Read,
    retry_because: list[str] | None = None,
) -> Drafted:
    """One attempt. `retry_because` is what the guards said about the last one."""
    ctx = TenantContext(
        tenant_id=tenant_id,
        # The worker has no user. The tools read with tenant scope only, which
        # is what grounds a draft in the conversation rather than in whatever
        # one salesperson happens to be allowed to see.
        user=AuthedUser(id=run_id, email=None, claims={}),
        role="sales",
    )
    answer = await converse(
        TaskKind.SALES_REPLY,
        ctx=ctx,
        system=SystemLayers(
            role=load("_rules") + "\n\n" + load("sales_copilot"),
            tenant=_tenant_layer(ground),
            context=context_layer(ground, read),
        ),
        prompt=_instruction(ground, read, retry_because),
        tools=TOOLS,
        output_schema=Draft,
        run_id=run_id,
        max_turns=MAX_TOOL_CALLS,
        trace_name="copilot",
    )
    draft = answer.parsed if isinstance(answer.parsed, Draft) else None
    if draft is not None and not (draft.reply or draft.template_name):
        # A Draft with neither validates and says nothing. The composer would
        # show an empty box, which reads as a bug in the product rather than as
        # a model that had nothing to say.
        log.info("draft_was_empty", run_id=str(run_id))
        draft = None
    return Drafted(draft=draft, cost_usd=answer.cost_usd, tool_calls=tuple(answer.tool_calls))


def _instruction(ground: Ground, read: Read, retry_because: list[str] | None) -> str:
    parts = [
        f"The customer's intent is **{read.intent}**"
        + (f" ({read.dialect})" if read.dialect else "")
        + ". Write the reply the salesperson should send."
    ]
    if not ground.window_open:
        parts.append(
            "The 24-hour window is closed: set `template_name` to one of the approved "
            "templates above and fill `template_variables` in order. Leave `reply` null."
        )
    if retry_because:
        parts.append(
            "Your previous draft was rejected. Fix **exactly** these and change nothing "
            "else:\n" + "\n".join(f"- {reason}" for reason in retry_because)
        )
    return "\n\n".join(parts)


def _tenant_layer(ground: Ground) -> str:
    """Brand, playbook and the handful of facts every reply might need.

    Sorted, with no timestamps and nothing per-conversation: this layer sits
    above the context in the cached prefix, and anything varying per call
    caches nothing at all.
    """
    context = ground.context
    lines = [f"You write for {context['tenant_name']}, a car dealership and exporter in the UAE."]
    hours = ground.settings.business_hours
    if hours:
        lines.append(
            "Opening hours: "
            + ", ".join(
                f"{day} {hour.open:%H:%M}-{hour.close:%H:%M}" for day, hour in sorted(hours.items())
            )
        )
    lines.append(f"Prices are in {context['currency']}.")
    return "\n".join(lines)
