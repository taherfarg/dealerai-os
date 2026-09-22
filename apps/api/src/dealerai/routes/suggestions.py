"""What the AI proposed: read it, ask for another, say what became of it.

Two routers because the contract has two shapes — a conversation has *a*
suggestion, and a suggestion has an outcome (docs/sales/06-api-contract.md § 3).
"""

from __future__ import annotations

from datetime import UTC, datetime
from difflib import SequenceMatcher
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel

from ..core.errors import NotFound, Unusable
from ..db.queries import copilot as q
from ..db.session import tenant_session
from ..deps import Ctx, TenantContext, require_permission
from ..events.bus import emit

conversations_router = APIRouter(prefix="/v1/conversations", tags=["suggestions"])
router = APIRouter(prefix="/v1/suggestions", tags=["suggestions"])

Sender = Annotated[TenantContext, Depends(require_permission("inbox.send"))]

#: The four reasons the panel offers. Free text would be unreadable in
#: aggregate, and the eval report's discard column is the point of collecting
#: them at all.
DISCARD_REASONS = ("wrong_info", "wrong_tone", "not_needed", "other")


class Suggestion(BaseModel):
    id: UUID
    conversation_id: UUID
    for_message_id: UUID | None
    status: Literal["generating", "ready", "blocked", "superseded"]
    text: str | None
    template: dict[str, Any] | None
    language: str | None
    confidence: str | None
    intent: str | None
    sources: list[dict[str, Any]]
    actions: list[dict[str, Any]]
    needs_human: str | None
    blocked_reason: str | None
    created_at: datetime


@conversations_router.get("/{conversation_id}/suggestion", response_model=Suggestion | None)
async def get_suggestion(ctx: Ctx, conversation_id: UUID) -> dict[str, Any] | None:
    """The live draft, or null.

    Visibility is the conversation's, enforced by RLS on ai_suggestions — a
    draft on a colleague's conversation is not there, rather than forbidden.
    """
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        row = await conn.fetchrow(q.LIVE_SUGGESTION, conversation_id)
    return dict(row) if row else None


@conversations_router.post(
    "/{conversation_id}/suggestion/regenerate", status_code=status.HTTP_202_ACCEPTED
)
async def regenerate(ctx: Sender, conversation_id: UUID) -> dict[str, str]:
    """Ask for another one.

    `forced` skips the two staleness checks and nothing else: a person pressing
    this wants a draft for the conversation as it is now, even though they have
    already replied to it.

    The live draft is left alone. The handler supersedes it in the same
    transaction that claims the next one, so a worker that dies does not leave
    the salesperson looking at an empty panel.
    """
    async with (
        tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn,
        conn.transaction(),
    ):
        latest = await conn.fetchval(q.LATEST_INBOUND, conversation_id)
        if latest is None:
            raise Unusable("There is nothing from the customer to reply to yet.")
        await emit(
            conn,
            "copilot.draft_requested",
            {
                "conversation_id": str(conversation_id),
                "message_id": str(latest),
                "forced": True,
            },
            tenant_id=ctx.tenant_id,
            # Keyed on the person and the minute, not on the message: one
            # salesperson mashing Regenerate should not queue five runs, and a
            # colleague asking a minute later should still get one.
            dedupe_key=f"redraft:{conversation_id}:{ctx.user.id}:{datetime.now(UTC):%Y%m%d%H%M}",
            priority=6,
        )
    return {"status": "accepted"}


class OutcomeIn(BaseModel):
    outcome: Literal["sent", "edited", "discarded"]
    final_text: str | None = None
    reason: str | None = None


@router.post("/{suggestion_id}/outcome", status_code=status.HTTP_204_NO_CONTENT)
async def record_outcome(ctx: Sender, suggestion_id: UUID, body: OutcomeIn) -> None:
    """Say what became of a draft.

    Sending one records itself, in the same transaction as the message
    (routes/inbox.py). This is how Dismiss is recorded, and it is the reason
    the discard column in the eval report has anything in it.
    """
    if body.reason is not None and body.reason not in DISCARD_REASONS:
        raise Unusable(f"reason is one of {', '.join(DISCARD_REASONS)}")
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        row = await conn.fetchrow("select text from ai_suggestions where id = $1", suggestion_id)
        if row is None:
            raise NotFound("no such suggestion")
        # Already answered for. Not an error: two tabs, one draft, and the
        # second click should be quiet rather than loud.
        await conn.fetchval(
            q.RECORD_OUTCOME,
            suggestion_id,
            body.outcome,
            ctx.user.id,
            edit_ratio(row["text"], body.final_text),
            body.reason,
            None,
        )


def edit_ratio(draft: str | None, final: str | None) -> float | None:
    """How much of the draft survived. 0.0 means it was sent word for word.

    docs/sales/04-ai-copilot.md § 3: `1 − SequenceMatcher(draft, final).ratio()`,
    and `<= 0.2` counts as accepted in the headline metric. Fixing a name is not
    rewriting a reply, and a metric that says otherwise would report a working
    feature as a failing one.
    """
    if not draft or final is None:
        return None
    return round(1 - SequenceMatcher(None, draft, final).ratio(), 3)
