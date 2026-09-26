"""The only way an agent reads a document.

A tool rather than always-on context because most messages are about a car, and
retrieving a policy for them is latency the customer waits through. The draft
handler retrieves up front for the intents that need it
(sales/grounding.py NEEDS_KNOWLEDGE); this is for the model's own follow-up
question, which is usually more specific than the one we guessed.
"""

from __future__ import annotations

from typing import Any

from ..deps import TenantContext
from ..sales.knowledge import search
from .registry import tool

GROUP = "knowledge"


@tool(name="search_knowledge", group=GROUP)
async def search_knowledge(ctx: TenantContext, *, question: str) -> list[dict[str, Any]]:
    """Search this dealership's own policies, FAQs and document sheets.

    Use it for export and shipping, customs and paperwork, financing terms,
    trade-in rules, warranty, and anything about how this dealership does
    business. Ask it a full question in the customer's own words.

    It knows nothing about cars, prices or stock — those come from
    search_inventory and get_vehicle. Quote what comes back as the dealership's
    own policy. If nothing comes back, say you will check.
    """
    passages = await search(ctx.tenant_id, question)
    return [
        {
            "chunk_id": passage.chunk_id,
            "document": passage.title,
            "section": passage.heading,
            "text": passage.content,
        }
        for passage in passages
    ]
