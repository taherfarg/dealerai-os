"""The tool registry: what an agent can do, and the only way it can do it.

A tool is a plain async function with a typed signature, a docstring the model
reads, and `TenantContext` as its first argument. The declaration the model sees
is generated from that signature, so the schema cannot drift from the code.

**Least privilege is enforced by construction.** An agent's tool list is fixed in
Python. The Copywriter cannot publish; the Community Manager cannot change a
price. That is a code-level constraint, not a sentence in a prompt that a
sufficiently confused model can talk itself past.

`ctx` is never in the declaration. The model does not choose which tenant it is
acting for — the executor does, from the run row — and a tenant id the model
could name is a tenant id it could name wrongly.
"""

from __future__ import annotations

import inspect
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, get_type_hints

import structlog
from google.genai import types
from pydantic import BaseModel, ValidationError, create_model

from ..db.session import tenant_session
from ..deps import TenantContext

log = structlog.get_logger()

#: Arguments and results are truncated before they reach a trace row. A trace is
#: for understanding what an agent did, not for keeping a second copy of the
#: customer database.
MAX_TRACE_CHARS = 2000


class ToolError(Exception):
    """Something the model should see and can act on.

    Raised for a bad argument or a missing entity — never for a bug. The message
    goes back into the conversation as the tool's result, so it is written for
    the model to read.
    """


@dataclass(frozen=True, slots=True)
class Tool:
    name: str
    group: str
    description: str
    fn: Callable[..., Awaitable[Any]]
    params: type[BaseModel]
    #: Mutating tools also write audit_log. Reading is traced; changing is
    #: answerable.
    mutates: bool

    def declaration(self) -> types.FunctionDeclaration:
        return types.FunctionDeclaration(
            name=self.name,
            description=self.description,
            parameters_json_schema=self.params.model_json_schema(),
        )


_REGISTRY: dict[str, Tool] = {}


def _params_model(fn: Callable[..., Any], name: str) -> type[BaseModel]:
    """Build a validation model from the function's keyword-only parameters.

    Pydantic already knows how to turn a typed signature into a strict JSON
    schema, so hand-rolling a type mapper would be a second, worse implementation
    that drifts from the first.

    Keyword-only on purpose: the model supplies arguments by name, and a
    positional parameter is one the declaration cannot describe.
    """
    signature = inspect.signature(fn)
    # Resolved, not raw: every module here uses `from __future__ import
    # annotations`, so param.annotation is the *string* "Literal['post', ...]"
    # and the model Pydantic builds from it cannot see what Literal is.
    hints = get_type_hints(fn)
    fields: dict[str, Any] = {}
    for index, (param_name, param) in enumerate(signature.parameters.items()):
        if index == 0:
            continue  # ctx
        if param.kind is not inspect.Parameter.KEYWORD_ONLY:
            raise TypeError(f"{name}: {param_name!r} must be keyword-only")
        if param_name not in hints:
            raise TypeError(f"{name}: {param_name!r} needs a type annotation")
        default = ... if param.default is inspect.Parameter.empty else param.default
        fields[param_name] = (hints[param_name], default)
    return create_model(f"{name}_params", **fields)


def tool(
    *, name: str, group: str, mutates: bool = False
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    def decorate(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        if name in _REGISTRY:
            raise ValueError(f"tool {name!r} is already registered")
        description = inspect.getdoc(fn)
        if not description:
            # The docstring is what the model reads to decide whether to call
            # this. A tool without one is a tool it will use wrongly.
            raise TypeError(f"{name}: a tool needs a docstring")
        _REGISTRY[name] = Tool(
            name=name,
            group=group,
            description=description,
            fn=fn,
            params=_params_model(fn, name),
            mutates=mutates,
        )
        return fn

    return decorate


def get(name: str) -> Tool | None:
    return _REGISTRY.get(name)


def names() -> frozenset[str]:
    return frozenset(_REGISTRY)


def in_group(group: str) -> list[str]:
    return sorted(t.name for t in _REGISTRY.values() if t.group == group)


def declarations(names_wanted: list[str]) -> list[types.Tool]:
    """The `types.Tool` list for a gateway call.

    One Tool holding every declaration, not one per tool: Gemini treats them as
    a single set, and the gateway sorts tools to keep the cached prefix stable.
    """
    unknown = set(names_wanted) - names()
    if unknown:
        raise ValueError(f"no such tool: {', '.join(sorted(unknown))}")
    declared = [_REGISTRY[n].declaration() for n in sorted(names_wanted)]
    return [types.Tool(function_declarations=declared)] if declared else []


def _encode(value: Any) -> Any:
    """JSON for the types asyncpg hands back.

    Numeric columns arrive as Decimal and datetimes as datetime, and neither is
    JSON. The model never sees the difference; what it saw before this existed
    was the whole task failing after the tool had already succeeded.
    """
    if isinstance(value, Decimal):
        # int when it is one: a model reading "days_in_stock: 75.0" starts
        # writing "75.0 days".
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    return str(value)


def jsonable(value: Any) -> Any:
    """The same value, made of things JSON has."""
    return json.loads(json.dumps(value, default=_encode))


def _truncate(value: Any) -> str:
    try:
        text = json.dumps(value, default=_encode)
    except (TypeError, ValueError):  # pragma: no cover - _encode covers ~everything
        text = repr(value)
    return text[:MAX_TRACE_CHARS]


async def call(
    name: str,
    ctx: TenantContext,
    arguments: dict[str, Any],
    *,
    run_id: Any = None,
    task_id: Any = None,
) -> Any:
    """Validate, dispatch, and trace one tool call.

    Every failure mode returns through `ToolError` rather than raising into the
    agent loop, because the model is the one that has to recover: "no vehicle
    with that id" is information it can act on, and a stack trace is not.
    """
    entry = _REGISTRY.get(name)
    if entry is None:
        raise ToolError(f"there is no tool called {name!r}")

    try:
        validated = entry.params.model_validate(arguments)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first["loc"]) or "arguments"
        raise ToolError(f"{name}: {where} — {first['msg']}") from exc

    started = time.perf_counter()
    status, error, result = "ok", None, None
    try:
        result = await entry.fn(ctx, **validated.model_dump())
    except ToolError as exc:
        status, error = "error", str(exc)
        raise
    finally:
        await _trace(
            ctx,
            entry,
            arguments=validated.model_dump(),
            result=result,
            status=status,
            error=error,
            latency_ms=int((time.perf_counter() - started) * 1000),
            run_id=run_id,
            task_id=task_id,
        )
    return result


_TRACE = """
insert into agent_traces
  (tenant_id, run_id, task_id, kind, name, latency_ms, status, error, payload)
values ($1,$2,$3,'tool',$4,$5,$6,$7,$8)
"""


async def _trace(
    ctx: TenantContext,
    entry: Tool,
    *,
    arguments: dict[str, Any],
    result: Any,
    status: str,
    error: str | None,
    latency_ms: int,
    run_id: Any,
    task_id: Any,
) -> None:
    async with tenant_session(ctx.tenant_id) as conn:
        await conn.execute(
            _TRACE,
            ctx.tenant_id,
            run_id,
            task_id,
            entry.name,
            latency_ms,
            status,
            error,
            {"arguments": _truncate(arguments), "result": _truncate(result)},
        )
    log.info(
        "tool_call",
        tool=entry.name,
        tenant_id=str(ctx.tenant_id),
        status=status,
        latency_ms=latency_ms,
    )
