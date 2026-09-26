"""What the customer is asking for, in one cheap call.

Thinking is off — ai/models.py routes CLASSIFY_INTENT to Flash Lite — because
this sits on the critical path of a reply and classification does not get
better for thinking about it.

Everything downstream reads this: which documents to retrieve, whether a lead
is created, which confidence band the draft lands in, and whether the whole
conversation stops because the customer said stop. So it is
schema-constrained, and an intent this codebase has no label for cannot be
returned at all.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from ...ai.gateway import SystemLayers, complete
from ...ai.models import TaskKind
from ...ai.prompts import load

IntentName = Literal[
    "greeting",
    "price",
    "availability",
    "specs",
    "export_shipping",
    "financing",
    "trade_in",
    "visit_test_drive",
    "documents_payment",
    "negotiation",
    "complaint",
    "human_request",
    "opt_out",
    "other",
]

#: The same list, iterable. Kept identical to `Intent` in
#: docs/sales/contract/types.ts, because the browser shows a label for each one
#: — test_intent.py fails if they drift.
INTENTS: tuple[str, ...] = (
    "greeting",
    "price",
    "availability",
    "specs",
    "export_shipping",
    "financing",
    "trade_in",
    "visit_test_drive",
    "documents_payment",
    "negotiation",
    "complaint",
    "human_request",
    "opt_out",
    "other",
)

#: How much of the conversation the classifier reads. Enough for "and the white
#: one?" to mean something, short enough to stay cheap.
TAIL = 8


class Entities(BaseModel):
    make: str = ""
    model: str = ""
    model_year: int | None = None
    colour: str = ""
    fuel: str = ""
    #: Minor units, like every other amount in this codebase.
    budget_minor: int | None = None
    #: ISO-2, and only when the customer named where the car is going.
    destination_country: str = ""


class Read(BaseModel):
    intent: IntentName
    confidence: float = Field(ge=0, le=1)
    language: Literal["ar", "en", "fr", "other"]
    script: Literal["arabic", "latin"]
    dialect: str = ""
    urgency: Literal["low", "normal", "high"] = "normal"
    entities: Entities = Field(default_factory=Entities)
    opt_out: bool = False

    @property
    def reply_language(self) -> Literal["ar", "en", "fr"]:
        """What we write back in.

        `other` becomes English, which is what a UAE dealership does when a
        message arrives in Urdu or Tagalog — and the draft schema has no room
        for a fourth language anyway.
        """
        return "en" if self.language == "other" else self.language


@dataclass(frozen=True, slots=True)
class Classified:
    read: Read
    cost_usd: float


#: What we assume when the model returns nothing usable. `other` at zero
#: confidence lands the draft in the low band, which sends it to a person —
#: the correct outcome for a message nobody understood.
UNREADABLE = Read(intent="other", confidence=0.0, language="en", script="latin")


async def classify(
    *,
    tenant_id: UUID,
    run_id: UUID | None,
    conversation_tail: Sequence[tuple[str, str]],
) -> Classified:
    """`conversation_tail` is (direction, text), oldest first. 'in' is the customer."""
    lines = "\n".join(
        f"{'customer' if direction == 'in' else 'us'}: {text}"
        for direction, text in conversation_tail
    )
    result = await complete(
        TaskKind.CLASSIFY_INTENT,
        tenant_id=tenant_id,
        system=SystemLayers(role=load("_rules") + "\n\n" + load("intent")),
        messages=f"## The conversation so far\n<untrusted>\n{lines}\n</untrusted>",
        output_schema=Read,
        run_id=run_id,
        trace_name="intent",
    )
    read = result.parsed if isinstance(result.parsed, Read) else UNREADABLE
    return Classified(read=read, cost_usd=result.cost_usd)
