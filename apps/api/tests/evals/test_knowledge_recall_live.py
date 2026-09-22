"""Does an Arabic question find an English policy?

This is the check that picks the embedding model, and the only justification
for the dimension in migration 0010. If recall@4 drops below the bar, the model
or its dimension is wrong: change ai/models.py, not this file.

The 50-question check in docs/sales/04-ai-copilot.md § 7 runs against Pollux's
real documents once S5 has imported them. This is the committed stand-in — 20
questions over three synthetic policies where the right paragraph is known.

Costs a fraction of a cent and needs GOOGLE_API_KEY.
"""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from pathlib import Path

import asyncpg
import pytest

from conftest import TENANT_A
from dealerai.ai.embeddings import embed, literal
from dealerai.sales import knowledge

pytestmark = pytest.mark.eval

HERE = Path(__file__).parent / "sales"

#: Overall, and for the cross-language half separately — averaging the two
#: hides the case that is actually hard.
RECALL_AT_4 = 0.9
RECALL_AT_4_CROSS_LANGUAGE = 0.85


async def _load_the_policies(su: asyncpg.Connection) -> None:
    for path in sorted((HERE / "policies").glob("*.md")):
        text = path.read_text("utf-8")
        pieces = knowledge.chunk(text)
        vectors = await embed(
            [knowledge.embeddable(piece) for piece in pieces],
            tenant_id=TENANT_A,
            kind="document",
        )
        document_id = await su.fetchval(
            """insert into documents (tenant_id, kind, title, source, status)
               values ($1, 'export_policy', $2, 'upload', 'ready') returning id""",
            TENANT_A,
            path.stem,
        )
        for piece, vector in zip(pieces, vectors, strict=True):
            await su.execute(
                """insert into doc_chunks
                     (tenant_id, document_id, chunk_index, content, embedding, meta)
                   values ($1,$2,$3,$4,$5::vector,$6::jsonb)""",
                TENANT_A,
                uuid.UUID(str(document_id)),
                piece.index,
                piece.content,
                literal(vector),
                json.dumps({"heading": piece.heading}),
            )


async def test_a_question_finds_the_paragraph_that_answers_it(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    await _load_the_policies(su)
    questions = json.loads((HERE / "recall.json").read_text("utf-8"))

    hits: dict[str, list[bool]] = defaultdict(list)
    missed: list[str] = []
    for item in questions:
        passages = await knowledge.search(TENANT_A, item["q"], use=4)
        found = any(passage.heading == item["expect"] for passage in passages)
        hits[item["lang"]].append(found)
        hits["all"].append(found)
        if not found:
            missed.append(f"{item['lang']}: {item['q']} → {[p.heading for p in passages]}")

    def rate(rows: list[bool]) -> float:
        return sum(rows) / len(rows) if rows else 0.0

    cross = hits["ar"] + hits["fr"]
    report = (
        f"recall@4 overall {rate(hits['all']):.0%} "
        f"(en {rate(hits['en']):.0%}, ar {rate(hits['ar']):.0%}, fr {rate(hits['fr']):.0%}); "
        f"cross-language {rate(cross):.0%}\nmissed:\n  " + "\n  ".join(missed)
    )
    print("\n" + report)

    assert rate(hits["all"]) >= RECALL_AT_4, report
    assert rate(cross) >= RECALL_AT_4_CROSS_LANGUAGE, report
