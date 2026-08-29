"""The single entry point for every model call in the system.

It picks the model, lays the prompt out so caching works, enforces the tenant's
monthly budget, and writes an agent_traces row. Nothing else in the codebase
constructs an Anthropic client.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import structlog
from anthropic import AsyncAnthropic
from anthropic.types import Message, MessageParam, TextBlock, TextBlockParam, ToolParam
from pydantic import BaseModel, ValidationError

from ..config import get_settings
from ..core.errors import AppError, BudgetExceeded
from ..db.session import tenant_session
from .models import ModelSpec, TaskKind, cost_usd, spec_for

log = structlog.get_logger()

_client: AsyncAnthropic | None = None


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

    Caching is a prefix match, so one changed byte invalidates everything after
    it. Layers are emitted in this order and the cache breakpoint goes after
    `tenant`:

        role    frozen per deploy
        tenant  brand brain + playbook, changes maybe weekly   <- breakpoint
        context retrieved for this request, varies every time

    Never put a timestamp, a request id, or an unsorted dict in `role` or
    `tenant`. That is a silent 5x on the bill, which is why
    test_gateway.py asserts the layout rather than trusting the convention.
    """

    role: str
    tenant: str = ""
    context: str = ""


@dataclass(slots=True)
class Completion:
    text: str
    message: Message
    spec: ModelSpec
    cost_usd: float
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    latency_ms: int
    parsed: BaseModel | None = None
    system_blocks: list[TextBlockParam] = field(default_factory=list)


def get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        key = get_settings().anthropic_api_key
        if not key:
            raise MissingAPIKey("ANTHROPIC_API_KEY is not set")
        _client = AsyncAnthropic(api_key=key)
    return _client


def build_system(layers: SystemLayers) -> list[TextBlockParam]:
    """Emit the system prompt with exactly one cache breakpoint.

    The breakpoint sits on the last stable layer, so everything above it — the
    role, and the tenant's brand brain and playbook — is billed at cache-read
    rates after the first call.
    """
    blocks: list[TextBlockParam] = [{"type": "text", "text": layers.role}]
    if layers.tenant:
        blocks.append({"type": "text", "text": layers.tenant})
    blocks[-1]["cache_control"] = {"type": "ephemeral", "ttl": "1h"}
    if layers.context:
        blocks.append({"type": "text", "text": layers.context})
    return blocks


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
    usage_input: int,
    usage_output: int,
    cache_read: int,
    cache_write: int,
    cost: float,
    latency_ms: int,
    status: str,
    error: str | None,
) -> None:
    async with tenant_session(tenant_id) as conn:
        await conn.execute(
            _TRACE_SQL,
            tenant_id,
            run_id,
            task_id,
            name,
            spec.model,
            usage_input,
            usage_output,
            cache_read,
            cache_write,
            cost,
            latency_ms,
            status,
            error,
            {"effort": spec.effort},
        )


def _text_of(message: Message) -> str:
    # isinstance, not a .type string check: content also carries thinking and
    # tool_use blocks, and only isinstance narrows the union for the type checker.
    return "".join(b.text for b in message.content if isinstance(b, TextBlock))


async def complete(
    task: TaskKind,
    *,
    tenant_id: UUID,
    system: SystemLayers,
    messages: list[MessageParam],
    run_id: UUID | None = None,
    task_id: UUID | None = None,
    tools: list[ToolParam] | None = None,
    output_schema: type[BaseModel] | None = None,
    max_tokens: int | None = None,
    trace_name: str | None = None,
) -> Completion:
    spec = spec_for(task)
    await assert_within_budget(tenant_id)

    kwargs: dict[str, Any] = {
        "model": spec.model,
        "max_tokens": max_tokens or spec.max_tokens,
        "system": build_system(system),
        "messages": messages,
        # Adaptive thinking only. ThinkingConfigAdaptiveParam has no
        # budget_tokens field — that belongs to the older "enabled" variant and
        # is rejected by these models.
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": spec.effort},
    }

    if tools:
        # Tools render ahead of the system prompt in the cache prefix, so a
        # non-deterministic order silently destroys every cache hit.
        kwargs["tools"] = sorted(tools, key=lambda t: t["name"])

    if output_schema is not None:
        kwargs["output_config"]["format"] = {
            "type": "json_schema",
            "schema": output_schema.model_json_schema(),
        }

    started = time.perf_counter()
    client = get_client()
    # One call path: always stream and take the final message. Long
    # non-streaming requests are rejected by the SDK, and having a single path
    # means the cache and cost accounting cannot diverge between two branches.
    async with client.messages.stream(**kwargs) as stream:
        message = await stream.get_final_message()
    latency_ms = int((time.perf_counter() - started) * 1000)

    usage = message.usage
    cache_read = usage.cache_read_input_tokens or 0
    cache_write = usage.cache_creation_input_tokens or 0
    cost = cost_usd(
        spec,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
    )

    name = trace_name or str(task)
    await _write_trace(
        tenant_id=tenant_id,
        run_id=run_id,
        task_id=task_id,
        name=name,
        spec=spec,
        usage_input=usage.input_tokens,
        usage_output=usage.output_tokens,
        cache_read=cache_read,
        cache_write=cache_write,
        cost=cost,
        latency_ms=latency_ms,
        status=message.stop_reason or "unknown",
        error=None,
    )

    log.info(
        "model_call",
        task=str(task),
        model=spec.model,
        cost_usd=round(cost, 6),
        cache_read=cache_read,
        latency_ms=latency_ms,
        stop_reason=message.stop_reason,
    )

    # Check the stop reason before touching content: on a refusal the content
    # blocks are not an answer.
    if message.stop_reason == "refusal":
        raise ModelRefusal(f"model refused during {task}")

    text = _text_of(message)
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
        message=message,
        spec=spec,
        cost_usd=cost,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
        latency_ms=latency_ms,
        parsed=parsed,
        system_blocks=kwargs["system"],
    )
