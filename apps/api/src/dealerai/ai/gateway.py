"""The single entry point for every model call in the system.

It picks the model, lays the prompt out so caching works, enforces the tenant's
monthly budget, and writes an agent_traces row. Nothing else in the codebase
constructs a model client.

Provider: Google Gemini via google-genai.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

import structlog
from google import genai
from google.genai import types
from pydantic import BaseModel, ValidationError

from ..config import get_settings
from ..core.errors import AppError, BudgetExceeded
from ..db.session import tenant_session
from .models import ModelSpec, TaskKind, cost_usd, spec_for

log = structlog.get_logger()

#: Explicit override. Tests monkeypatch this; nothing in production sets it.
_client: genai.Client | None = None

#: Real clients, keyed by the event loop that created them.
#:
#: The client holds an httpx connection pool bound to its loop. A single
#: module-level singleton works in production, where one loop lives for the
#: life of the process — but reuse it across two `asyncio.run()` calls and the
#: second one closes sockets on a dead loop ("Event loop is closed"). Keying on
#: the loop makes that impossible rather than merely unlikely.
_loop_clients: dict[int, genai.Client] = {}

#: Finish reasons that mean "the model declined", as opposed to a normal stop
#: or hitting max_tokens. Each is a refusal with a different cause, and the
#: cause is worth keeping — a SAFETY block on a customer reply is a prompt
#: problem, a RECITATION block is a content problem.
REFUSAL_REASONS = {
    types.FinishReason.SAFETY,
    types.FinishReason.RECITATION,
    types.FinishReason.BLOCKLIST,
    types.FinishReason.PROHIBITED_CONTENT,
    types.FinishReason.SPII,
    types.FinishReason.IMAGE_SAFETY,
}


class ModelRefusal(AppError):
    status = 422
    slug = "model-refusal"
    title = "The model declined to answer"


class ModelOutputInvalid(AppError):
    status = 422
    slug = "model-output-invalid"
    title = "Model output did not match the requested schema"


class MissingAPIKey(AppError):
    status = 503
    slug = "model-unavailable"
    title = "No model API key configured"


@dataclass(frozen=True, slots=True)
class SystemLayers:
    """The prompt, split by how often each part changes.

    Gemini caches implicitly on a repeated prefix, so ordering still decides
    whether anything is cached at all:

        role    frozen per deploy
        tenant  brand brain + playbook, changes maybe weekly
        context retrieved for this request, varies every time

    Unlike Anthropic there is no explicit breakpoint to place — the model finds
    the common prefix itself. What that means practically is that a timestamp or
    an unsorted dict in `role` or `tenant` does not merely move a breakpoint, it
    destroys the prefix and caches nothing at all. test_gateway.py asserts the
    ordering rather than trusting the convention.
    """

    role: str
    tenant: str = ""
    context: str = ""

    def render(self) -> str:
        return "\n\n".join(p for p in (self.role, self.tenant, self.context) if p)


@dataclass(slots=True)
class Completion:
    text: str
    response: types.GenerateContentResponse
    spec: ModelSpec
    cost_usd: float
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    thought_tokens: int
    latency_ms: int
    parsed: BaseModel | None = None
    system_instruction: str = ""


def get_client() -> genai.Client:
    if _client is not None:
        return _client

    try:
        loop_key = id(asyncio.get_running_loop())
    except RuntimeError:
        loop_key = 0

    client = _loop_clients.get(loop_key)
    if client is None:
        api_key = get_settings().google_api_key
        if not api_key:
            raise MissingAPIKey("GOOGLE_API_KEY is not set")
        client = genai.Client(api_key=api_key)
        _loop_clients[loop_key] = client
    return client


async def aclose_clients() -> None:
    """Close the client belonging to the current loop.

    Worth calling on shutdown and between tests; leaving sockets to be closed by
    the garbage collector is what produces "Event loop is closed" long after the
    code that opened them has finished.
    """
    try:
        loop_key = id(asyncio.get_running_loop())
    except RuntimeError:
        loop_key = 0
    client = _loop_clients.pop(loop_key, None)
    if client is not None:
        await client.aio.aclose()


_BUDGET_SQL = """
select t.monthly_ai_budget_usd::float8 as budget,
       coalesce((
         select sum(tr.cost_usd) from agent_traces tr
         where tr.tenant_id = t.id and tr.created_at >= date_trunc('month', now())
       ), 0)::float8 as spent
from tenants t
where t.id = $1
"""


async def assert_within_budget(tenant_id: UUID) -> float:
    """Raise before spending money, not after. Returns spend so far this month."""
    async with tenant_session(tenant_id) as conn:
        row = await conn.fetchrow(_BUDGET_SQL, tenant_id)
    if row is None:
        raise BudgetExceeded(f"unknown tenant {tenant_id}")
    if row["spent"] >= row["budget"]:
        raise BudgetExceeded(
            f"tenant has spent ${row['spent']:.2f} of its ${row['budget']:.2f} monthly budget"
        )
    return float(row["spent"])


_TRACE_SQL = """
insert into agent_traces (
    tenant_id, run_id, task_id, kind, name, model,
    input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
    cost_usd, latency_ms, status, error, payload
) values ($1,$2,$3,'model',$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
"""


async def _write_trace(
    *,
    tenant_id: UUID,
    run_id: UUID | None,
    task_id: UUID | None,
    name: str,
    spec: ModelSpec,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int,
    thought_tokens: int,
    cost: float,
    latency_ms: int,
    status: str,
) -> None:
    async with tenant_session(tenant_id) as conn:
        await conn.execute(
            _TRACE_SQL,
            tenant_id,
            run_id,
            task_id,
            name,
            spec.model,
            input_tokens,
            output_tokens,
            cached_tokens,
            # Gemini has no cache-write step — implicit caching costs nothing to
            # populate. The column stays for schema compatibility and reads 0.
            0,
            cost,
            latency_ms,
            status,
            None,
            {"thought_tokens": thought_tokens, "provider": "google"},
        )


def _text_of(response: types.GenerateContentResponse) -> str:
    """Concatenate answer text, skipping thought parts.

    `response.text` raises when a candidate has no text part, which happens on a
    safety block — and that is exactly when the caller most wants a clean error
    rather than an exception from a property access.
    """
    out: list[str] = []
    for candidate in response.candidates or []:
        for part in (candidate.content.parts if candidate.content else None) or []:
            if getattr(part, "thought", False):
                continue
            if part.text:
                out.append(part.text)
    return "".join(out)


def _tool_name(tool: Any) -> str:
    """Sort key for tools.

    GenerateContentConfig.tools is typed as Tool | Callable | Any because the
    SDK also accepts bare Python functions. We only ever pass declarations, but
    the key has to survive the wider type without narrowing wrongly.
    """
    decls = getattr(tool, "function_declarations", None)
    if decls:
        return str(decls[0].name or "")
    return str(getattr(tool, "__name__", ""))


def _finish_reason(response: types.GenerateContentResponse) -> types.FinishReason | None:
    for candidate in response.candidates or []:
        if candidate.finish_reason:
            return candidate.finish_reason
    return None


async def complete(
    task: TaskKind,
    *,
    tenant_id: UUID,
    system: SystemLayers,
    # The SDK's own alias. list[Content] does not satisfy it because list is
    # invariant, and hand-writing the union would drift the moment the SDK
    # widens it.
    messages: types.ContentListUnion,
    run_id: UUID | None = None,
    task_id: UUID | None = None,
    tools: list[types.Tool] | None = None,
    output_schema: type[BaseModel] | None = None,
    max_tokens: int | None = None,
    trace_name: str | None = None,
    input_kind: Literal["standard", "audio"] = "standard",
) -> Completion:
    spec = spec_for(task)
    await assert_within_budget(tenant_id)

    system_instruction = system.render()
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        max_output_tokens=max_tokens or spec.max_tokens,
        thinking_config=types.ThinkingConfig(thinking_budget=spec.thinking_budget),
        # Automatic function calling is ON by default and would have the SDK
        # execute tool callables itself, inside this call. That bypasses the
        # autonomy gate, every guard, and the trace — the entire safety model
        # sits in orchestrator/executor.py, which owns the tool loop. The SDK
        # must hand back function_call parts and do nothing with them.
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    if tools:
        # Tools are part of the cached prefix, so a non-deterministic order
        # silently destroys every cache hit.
        config.tools = sorted(tools, key=_tool_name)

    if output_schema is not None:
        # Schema-constrained decoding: the model cannot emit anything that fails
        # to parse, so the local validation below is a contract check rather
        # than a parser.
        config.response_mime_type = "application/json"
        config.response_schema = output_schema

    started = time.perf_counter()
    client = get_client()
    response = await client.aio.models.generate_content(
        model=spec.model, contents=messages, config=config
    )
    latency_ms = int((time.perf_counter() - started) * 1000)

    usage = response.usage_metadata
    input_tokens = (usage.prompt_token_count if usage else 0) or 0
    output_tokens = (usage.candidates_token_count if usage else 0) or 0
    cached_tokens = (usage.cached_content_token_count if usage else 0) or 0
    thought_tokens = (usage.thoughts_token_count if usage else 0) or 0

    cost = cost_usd(
        spec,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_tokens=cached_tokens,
        thought_tokens=thought_tokens,
        input_kind=input_kind,
    )

    reason = _finish_reason(response)
    await _write_trace(
        tenant_id=tenant_id,
        run_id=run_id,
        task_id=task_id,
        name=trace_name or str(task),
        spec=spec,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_tokens=cached_tokens,
        thought_tokens=thought_tokens,
        cost=cost,
        latency_ms=latency_ms,
        status=str(reason.value) if reason else "unknown",
    )

    log.info(
        "model_call",
        task=str(task),
        model=spec.model,
        cost_usd=round(cost, 6),
        cached_tokens=cached_tokens,
        thought_tokens=thought_tokens,
        latency_ms=latency_ms,
        finish_reason=str(reason.value) if reason else None,
    )

    # Check the finish reason before touching content: on a safety block there
    # is no text part at all, and `response.text` would raise instead of
    # producing the typed error a caller can act on.
    if reason in REFUSAL_REASONS:
        raise ModelRefusal(f"model declined during {task}: {reason.value if reason else '?'}")

    text = _text_of(response)
    parsed: BaseModel | None = None
    if output_schema is not None:
        try:
            parsed = output_schema.model_validate_json(text)
        except ValidationError as exc:
            raise ModelOutputInvalid(
                f"{output_schema.__name__} validation failed: {exc.error_count()} error(s)"
            ) from exc

    return Completion(
        text=text,
        response=response,
        spec=spec,
        cost_usd=cost,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_tokens=cached_tokens,
        thought_tokens=thought_tokens,
        latency_ms=latency_ms,
        parsed=parsed,
        system_instruction=system_instruction,
    )
