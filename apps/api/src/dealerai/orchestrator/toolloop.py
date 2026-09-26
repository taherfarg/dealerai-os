"""The tool loop: model, tools, model, until it stops asking.

Gemini has no agentic runner, and the gateway deliberately disables the SDK's
automatic function calling — letting it execute callables inside a single
request would bypass the autonomy gate, the guards and the traces all at once.
So the loop lives here, where cost accounting and tracing already belong.

Two phases, on purpose. The tool phase runs with declarations and no response
schema; the answer phase runs with a schema and no tools. Gemini refuses
schema-constrained decoding while function calling is enabled, and splitting it
also means the model is not choosing between calling a tool and filling in a
field on the same turn.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import structlog
from google.genai import types
from pydantic import BaseModel

from ..ai.gateway import SystemLayers, complete
from ..ai.models import TaskKind
from ..deps import TenantContext
from ..tools import registry

log = structlog.get_logger()

#: A model that keeps calling tools is usually stuck in a loop rather than being
#: thorough, and every turn costs money. Six is enough for search, read, check.
MAX_TURNS = 6


@dataclass(slots=True)
class Conversation:
    text: str = ""
    parsed: BaseModel | None = None
    cost_usd: float = 0.0
    tool_calls: list[str] = field(default_factory=list)
    turns: int = 0
    hit_turn_limit: bool = False


def _function_calls(response: types.GenerateContentResponse) -> list[types.FunctionCall]:
    calls: list[types.FunctionCall] = []
    for candidate in response.candidates or []:
        for part in (candidate.content.parts if candidate.content else None) or []:
            if part.function_call:
                calls.append(part.function_call)
    return calls


async def _run_tool(call: types.FunctionCall, ctx: TenantContext, ids: dict[str, Any]) -> Any:
    """Execute one call, turning every failure into something the model can read.

    A tool that raises into the loop ends the task. A tool that returns "no
    vehicle with that id" lets the model say so, which is the entire point of
    giving it tools instead of letting it remember.
    """
    try:
        result = await registry.call(call.name or "", ctx, dict(call.args or {}), **ids)
    except registry.ToolError as exc:
        return {"error": str(exc)}
    # Made of JSON before it goes back to the SDK. A numeric column arrives as a
    # Decimal, and handing one to a FunctionResponse fails the whole task after
    # the tool has already done its work — which reads as a tool failure and is
    # not one.
    return registry.jsonable(result)


async def converse(
    task: TaskKind,
    *,
    ctx: TenantContext,
    system: SystemLayers,
    prompt: str,
    tools: list[str],
    output_schema: type[BaseModel] | None = None,
    run_id: UUID | None = None,
    task_id: UUID | None = None,
    max_turns: int = MAX_TURNS,
    trace_name: str | None = None,
) -> Conversation:
    """Talk to the model, running whatever tools it asks for, until it answers."""
    declared = registry.declarations(tools)
    ids = {"run_id": run_id, "task_id": task_id}
    # Typed as the SDK's own element alias, not list[Content]: list is
    # invariant, so a list[Content] satisfies no arm of ContentListUnion.
    contents: list[types.ContentUnion] = [
        types.Content(role="user", parts=[types.Part.from_text(text=prompt)])
    ]
    out = Conversation()

    for turn in range(max_turns):
        if not declared and output_schema is not None:
            # With nothing to call, this phase could only write the answer as
            # free text for the next to write again as JSON: a model turn of a
            # waiting customer, bought for nothing.
            break
        out.turns = turn + 1
        result = await complete(
            task,
            tenant_id=ctx.tenant_id,
            system=system,
            messages=list(contents),
            tools=declared or None,
            run_id=run_id,
            task_id=task_id,
            trace_name=trace_name or f"{task}:tools",
        )
        out.cost_usd += result.cost_usd

        calls = _function_calls(result.response)
        if not calls:
            out.text = result.text
            if result.text:
                # Kept, so the answer phase formats this answer rather than
                # writing a second one from nothing. Dropped, the model was
                # asked for "what the tools returned" when no tool had run — and
                # the copilot eval got seven empty drafts out of twenty-three.
                contents.append(
                    types.Content(role="model", parts=[types.Part.from_text(text=result.text)])
                )
            break

        contents.append(
            types.Content(role="model", parts=[types.Part(function_call=c) for c in calls])
        )
        responses: list[types.Part] = []
        for call in calls:
            out.tool_calls.append(call.name or "?")
            value = await _run_tool(call, ctx, ids)
            responses.append(
                types.Part.from_function_response(name=call.name or "", response={"result": value})
            )
        contents.append(types.Content(role="user", parts=responses))
    else:
        # Fell out of the loop still calling tools. Better to report it than to
        # keep paying, and the caller decides whether a partial answer is usable.
        out.hit_turn_limit = True
        log.warning("tool_loop_turn_limit", turns=max_turns, calls=out.tool_calls)

    if output_schema is not None:
        # The answer phase: same conversation, schema on, tools off.
        final = await complete(
            task,
            tenant_id=ctx.tenant_id,
            system=system,
            messages=list(contents)
            + [
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_text(
                            text="Now give your final answer in the required format, using "
                            "only the facts you were given and what any tools returned."
                        )
                    ],
                )
            ],
            output_schema=output_schema,
            run_id=run_id,
            task_id=task_id,
            trace_name=f"{trace_name or task}:answer",
        )
        out.cost_usd += final.cost_usd
        out.text = final.text
        out.parsed = final.parsed

    return out
