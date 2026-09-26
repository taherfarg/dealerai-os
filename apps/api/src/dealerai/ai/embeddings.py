"""Vectors, from the same client and under the same budget as everything else.

A separate module from gateway.py because embedding is a different API call
with no candidates, no finish reason and no schema — but it shares the client,
the budget check and the trace, because a tenant's monthly ceiling means
nothing if one kind of model call is exempt from it.
"""

from __future__ import annotations

import math
import time
from collections.abc import Sequence
from typing import Literal, cast
from uuid import UUID

import structlog
from google.genai import types

from ..db.session import tenant_session
from .gateway import assert_within_budget, get_client
from .models import EMBEDDING, EMBEDDING_DIMENSIONS, cost_usd

log = structlog.get_logger()

#: Gemini takes a batch per request; this is the point past which one failure
#: costs too much work to redo.
BATCH = 32

#: Roughly four characters to a token. There is no tokenizer in this process and
#: the number is only ever used for the bill and the trace.
CHARS_PER_TOKEN = 4

_TRACE = """
insert into agent_traces
  (tenant_id, run_id, kind, name, model, input_tokens, output_tokens, cost_usd, latency_ms,
   status, payload)
values ($1,$2,'model','embed',$3,$4,0,$5,$6,'ok',$7)
"""


def _unit(vector: list[float]) -> list[float]:
    """Re-normalise a truncated embedding.

    Only the full 3072-dimension output is unit length. Truncate it and the
    norm drifts, and cosine distance — which the HNSW index is built on —
    quietly stops measuring what it claims to. This is one line and the reason
    for it is the entire correctness of retrieval.
    """
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector] if norm else vector


async def embed(
    texts: Sequence[str],
    *,
    tenant_id: UUID,
    kind: Literal["document", "query"],
    run_id: UUID | None = None,
) -> list[list[float]]:
    """Embed in the order given.

    `kind` decides the task type, and it matters: a query and a document are
    embedded into the same space by different instructions, and using one for
    both measurably costs recall.
    """
    if not texts:
        return []
    await assert_within_budget(tenant_id)
    client = get_client()
    config = types.EmbedContentConfig(
        task_type="RETRIEVAL_DOCUMENT" if kind == "document" else "RETRIEVAL_QUERY",
        output_dimensionality=EMBEDDING_DIMENSIONS,
    )

    vectors: list[list[float]] = []
    started = time.perf_counter()
    tokens = 0
    for start in range(0, len(texts), BATCH):
        window = texts[start : start + BATCH]
        # `list` is invariant, so a list[str] satisfies no arm of the SDK's
        # union even though a list of strings is exactly what it documents. The
        # cast is local and the runtime value is right; hand-writing the arm
        # would drift the moment the SDK widens it.
        response = await client.aio.models.embed_content(
            model=EMBEDDING.model,
            contents=cast(types.ContentListUnion, list(window)),
            config=config,
        )
        for embedding in response.embeddings or []:
            vectors.append(_unit(list(embedding.values or [])))
        tokens += sum(len(text) for text in window) // CHARS_PER_TOKEN

    latency_ms = int((time.perf_counter() - started) * 1000)
    cost = cost_usd(EMBEDDING, input_tokens=tokens, output_tokens=0)
    async with tenant_session(tenant_id) as conn:
        await conn.execute(
            _TRACE,
            tenant_id,
            run_id,
            EMBEDDING.model,
            tokens,
            cost,
            latency_ms,
            {"count": len(texts), "kind": kind, "dimensions": EMBEDDING_DIMENSIONS},
        )
    log.info("embedded", count=len(texts), kind=kind, cost_usd=round(cost, 6))
    if len(vectors) != len(texts):
        # Zipped against the chunks by the caller. A short list would silently
        # attach the wrong vector to the wrong paragraph, and retrieval would be
        # wrong rather than broken — the worse of the two.
        raise ValueError(f"asked for {len(texts)} embeddings and got {len(vectors)}")
    return vectors


def literal(vector: Sequence[float]) -> str:
    """A vector as pgvector's text input.

    asyncpg has no pgvector codec, and registering one for a type used by two
    queries is more moving parts than a `$1::vector` cast.
    """
    return "[" + ",".join(f"{value:.7f}" for value in vector) + "]"
