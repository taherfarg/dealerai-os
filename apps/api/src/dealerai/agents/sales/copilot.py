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

from ...ai.gateway import ModelOutputInvalid, SystemLayers
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

#: Answered from the conversation and the car it is about, both already in the
#: context layer. With nothing to look up, the draft is one model call.
NO_LOOKUP = frozenset(
    {"greeting", "human_request", "complaint", "negotiation", "visit_test_drive", "opt_out"}
)


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
    label: str
    #: create_lead
    vehicle_id: str | None = None
    #: create_task
    title: str | None = None
    due_at: str | None = None
    #: update_profile
    field: str | None = None
    value: str | None = None


class Draft(BaseModel):
    """What the model is allowed to produce, and nothing else.

    `reply` and `template_name` are the two ways to answer. A closed window
    makes the second mandatory: the instruction says so, and the handler checks
    it afterwards anyway, because an instruction is not an enforcement.
    """

    #: No max_length here, and that is deliberate. Schema-constrained decoding
    #: enforces structure and types, not string lengths — so a length cap fails
    #: the *whole draft* in the gateway rather than trimming it, and a reply
    #: that ran forty characters long becomes no reply at all. The real bound is
    #: `max_output_tokens` in ai/models.py; brevity is the prompt's job and the
    #: judge's.
    #:
    #: Required, and a string rather than nullable: schema decoding guarantees
    #: a required field and nothing else. Optional, the model answered a
    #: customer's "hi" with the reply in its tool-phase turn and a JSON of
    #: everything *but* the reply — one draft in seven came back empty. With a
    #: template it is "", and the template is what gets sent.
    reply: str
    template_name: str | None = None
    template_variables: list[str] = Field(default_factory=list, max_length=20)
    language: Literal["ar", "en", "fr"]
    used_vehicle_ids: list[str] = Field(default_factory=list, max_length=6)
    used_chunk_ids: list[int] = Field(default_factory=list, max_length=8)
    actions: list[ProposedAction] = Field(default_factory=list, max_length=2)
    needs_human: str | None = None


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
    rejected: str | None = None,
) -> Drafted:
    """One attempt. `retry_because` is what the guards said about `rejected`."""
    ctx = TenantContext(
        tenant_id=tenant_id,
        # The worker has no user. The tools read with tenant scope only, which
        # is what grounds a draft in the conversation rather than in whatever
        # one salesperson happens to be allowed to see.
        user=AuthedUser(id=run_id, email=None, claims={}),
        role="sales",
    )
    try:
        answer = await converse(
            TaskKind.SALES_REPLY,
            ctx=ctx,
            system=SystemLayers(
                role=load("_rules") + "\n\n" + load("sales_copilot"),
                tenant=_tenant_layer(ground),
                context=context_layer(ground, read),
            ),
            prompt=_instruction(ground, read, retry_because, rejected),
            tools=_tools(ground, read, retry_because),
            output_schema=Draft,
            run_id=run_id,
            max_turns=MAX_TOOL_CALLS,
            trace_name="copilot",
        )
    except ModelOutputInvalid as exc:
        # A reply that runs away until the output ceiling arrives as cut-off
        # JSON. That is one attempt with nothing usable, like an empty draft —
        # not an event to fail and replay from the top. Its cost is already in
        # agent_traces, which is what the budget counts.
        log.warning("draft_unparseable", run_id=str(run_id), because=str(exc))
        return Drafted(draft=None, cost_usd=0.0, tool_calls=())
    draft = answer.parsed if isinstance(answer.parsed, Draft) else None
    if draft is not None and not (draft.reply or draft.template_name):
        # A Draft with neither validates and says nothing. The composer would
        # show an empty box, which reads as a bug in the product rather than as
        # a model that had nothing to say.
        log.info("draft_was_empty", run_id=str(run_id))
        draft = None
    return Drafted(draft=draft, cost_usd=answer.cost_usd, tool_calls=tuple(answer.tool_calls))


def _tools(ground: Ground, read: Read, retry_because: list[str] | None) -> list[str]:
    """What this attempt may call — every name is a model turn a customer waits through.

    A retry rewrites wording; the facts are above and in the rejected draft, so
    it gets none and is one call rather than two — retries were the eval's
    whole latency tail. So do the intents a lookup cannot help. Passages
    already retrieved with the customer's own words leave `search_knowledge`
    re-reading them, which the eval caught nine times in forty drafts.
    """
    if retry_because or read.intent in NO_LOOKUP:
        return []
    return [name for name in TOOLS if not (name == "search_knowledge" and ground.chunks)]


def _instruction(
    ground: Ground, read: Read, retry_because: list[str] | None, rejected: str | None = None
) -> str:
    parts = [
        f"The customer's intent is **{read.intent}**"
        + (f" ({read.dialect})" if read.dialect else "")
        + ". Write the reply the salesperson should send.",
        # Every tool call is a model turn the customer waits through, and the
        # eval caught the model looking up cars it had already been handed.
        "The cars, prices and policy paragraphs you need are already above. Call a "
        "tool only for a car or a policy that is not there.",
    ]
    held = ground.reserved_asked_about(read)
    if held:
        # Said on the turn itself, for this car. The rule in the role layer and
        # beside the car's own status line both lost to "متوفر عندنا" — "we
        # have it" — in four of seven eval runs.
        parts.append(
            f"The {held} they asked about is reserved for another customer. Answer what "
            "they asked about it — its price included — say that it is reserved, and never "
            "call it available or in stock, in any language."
        )
    if read.reply_language == "ar" and read.script == "latin":
        # Said here as well as in the context layer: the eval's drafts to
        # "3andkom hilux?" came back in Arabic script, or in Latin letters with
        # "el سعر" in the middle.
        parts.append(
            "They write Arabic in Latin letters, so the whole reply is in Latin letters — "
            "not one word in Arabic script."
        )
    if not ground.window_open:
        parts.append(
            "The 24-hour window is closed: set `template_name` to one of the approved "
            "templates above and fill `template_variables` in order. Leave `reply` empty. "
            # "le prix de {{2}}" filled with "le Toyota Hilux" is "de le", which
            # is what the exit run's French preview said.
            "Each variable is the bare value — a name, a car, a price — without an article "
            "or any word the template already has around it."
        )
    if retry_because:
        parts.append(
            "Your previous draft was rejected. Fix **exactly** these and change nothing "
            "else:\n"
            + "\n".join(f"- {reason}" for reason in retry_because)
            # Without the draft itself "change nothing else" refers to nothing,
            # and a retry asked to fix a draft it could not see came back empty.
            + (
                f"\n\nThe rejected draft:\n<untrusted>\n{rejected}\n</untrusted>"
                if rejected
                else ""
            )
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
    else:
        # Said out loud, because the silence was filled: with nothing here the
        # eval's drafts told customers "9 AM to 8 PM", then "until 6 PM today".
        lines.append(
            'Opening hours are not set. Never state any, and never say "any time": '
            "offer one specific time and let the salesperson confirm it."
        )
    if ground.settings.arabic_register == "gulf":
        lines.append(
            "Write Arabic in a polite Gulf register, whatever dialect the customer writes in."
        )
    lines.append(f"Prices are in {context['currency']}.")
    return "\n".join(lines)
