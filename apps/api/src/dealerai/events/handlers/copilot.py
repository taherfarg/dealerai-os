"""Everything the copilot does when nobody asked it to.

One handler per event: a document was uploaded, a customer wrote, a
conversation went quiet, an hour passed.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog

from ...agents.sales import copilot
from ...agents.sales.copilot import Draft
from ...agents.sales.intent import Read, classify
from ...ai.embeddings import embed, literal
from ...ai.gateway import assert_within_budget
from ...core.errors import BudgetExceeded
from ...db.queries import copilot as q
from ...db.session import tenant_session
from ...guards import Finding, Findings
from ...guards import brand as brand_guard
from ...guards import commitments as commitments_guard
from ...guards import inventory as inventory_guard
from ...guards import pii as pii_guard
from ...guards import price as price_guard
from ...guards import script as script_guard
from ...media import storage
from ...sales import confidence, grounding, knowledge
from ...sales.grounding import Ground
from ...sales.knowledge import Passage, chunk, embeddable, extract
from ...sales.messaging import render_template
from ...sales.runs import Run, agent_run
from ...sales.timeline import event_line
from ..bus import Event, handler
from .notify import notify

log = structlog.get_logger()

#: Kept in the row rather than only in the log: the person who uploaded the
#: document is looking at Settings, not at the worker's output.
_MAX_ERROR = 500

#: Enough of the text to show a preview and to search; the chunks are what
#: retrieval actually reads.
_MAX_CONTENT = 100_000


# ---------------------------------------------------------------------------
# Knowledge documents
# ---------------------------------------------------------------------------


@handler("document.uploaded")
async def on_document_uploaded(event: Event) -> None:
    """Extract, chunk, embed."""
    if event.tenant_id is None:
        raise ValueError("document.uploaded requires a tenant")
    tenant_id = event.tenant_id
    document_id = UUID(str(event.payload["document_id"]))

    async with tenant_session(tenant_id) as conn:
        row = await conn.fetchrow(
            """update documents set status = 'processing', error = null
                where id = $1 and status in ('pending', 'failed')
                returning storage_path, meta, title""",
            document_id,
        )
    if row is None:
        return  # already processed, or deleted while it sat in the queue

    try:
        data = await storage.download(str(row["storage_path"]))
        text = extract(data, str((row["meta"] or {}).get("mime") or ""), row["title"])
        pieces = chunk(text)
        if not pieces:
            raise ValueError("no text could be read from this file")
        vectors = await embed(
            [embeddable(piece) for piece in pieces], tenant_id=tenant_id, kind="document"
        )
    except Exception as exc:  # noqa: BLE001 - every failure is the dealer's to see
        async with tenant_session(tenant_id) as conn:
            await conn.execute(
                "update documents set status = 'failed', error = $2 where id = $1",
                document_id,
                str(exc)[:_MAX_ERROR],
            )
        log.warning("document_failed", document_id=str(document_id), error=str(exc))
        return

    async with tenant_session(tenant_id) as conn, conn.transaction():
        # Replaced wholesale rather than appended: re-processing a document must
        # not leave the old chunks behind to be quoted alongside the new ones.
        await conn.execute("delete from doc_chunks where document_id = $1", document_id)
        await conn.executemany(
            """insert into doc_chunks
                 (tenant_id, document_id, chunk_index, content, embedding, meta)
               values ($1,$2,$3,$4,$5::vector,$6::jsonb)""",
            [
                (
                    tenant_id,
                    document_id,
                    piece.index,
                    piece.content,
                    literal(vector),
                    {"heading": piece.heading},
                )
                for piece, vector in zip(pieces, vectors, strict=True)
            ],
        )
        await conn.execute(
            "update documents set status = 'ready', content = $2 where id = $1",
            document_id,
            text[:_MAX_CONTENT],
        )
    log.info("document_ready", document_id=str(document_id), chunks=len(pieces))


# ---------------------------------------------------------------------------
# The draft loop — docs/sales/04-ai-copilot.md § 3
# ---------------------------------------------------------------------------

#: Intents that mean the customer is shopping, so a lead should exist
#: (docs/sales/04-ai-copilot.md § 5). Code creates it; the model only proposes
#: leads as chips a person clicks.
BUYING = frozenset(
    {
        "price",
        "availability",
        "visit_test_drive",
        "export_shipping",
        "negotiation",
        "documents_payment",
    }
)

#: How much of the conversation the classifier reads.
CLASSIFY_TAIL = 8


@handler("copilot.draft_requested")
async def on_draft_requested(event: Event) -> None:
    """Draft a reply, or decide — in code — not to."""
    if event.tenant_id is None:
        raise ValueError("copilot.draft_requested requires a tenant")
    tenant_id = event.tenant_id
    conversation_id = UUID(str(event.payload["conversation_id"]))
    message_id = UUID(str(event.payload["message_id"]))
    forced = bool(event.payload.get("forced"))

    async with tenant_session(tenant_id) as conn:
        await conn.execute(q.RELEASE_STALE, conversation_id)
        row = await conn.fetchrow(q.DRAFT_PRECONDITIONS, conversation_id, message_id)

    if row is None:
        return
    because = _why_not(row, message_id, forced=forced)
    if because is not None:
        # Every one of these is a normal outcome, logged and left alone: a
        # conversation nobody wants a draft for is not an error.
        log.info("draft_skipped", conversation_id=str(conversation_id), because=because)
        return

    try:
        # The seventh refusal, and the only one that needs its own query: the
        # gateway enforces the ceiling anyway, but it does so from inside the
        # first model call, which by then has cost a run row and an exception
        # out of the middle of the loop. docs/sales/04-ai-copilot.md § 3 puts
        # the budget with the other preconditions, and this is where it goes.
        await assert_within_budget(tenant_id)
        async with agent_run(
            tenant_id,
            goal="draft a reply",
            goal_input={"conversation_id": str(conversation_id), "message_id": str(message_id)},
        ) as run:
            await _draft(tenant_id, conversation_id, message_id, run)
    except BudgetExceeded as exc:
        # Never a failed event: a tenant at its ceiling has no reply coming
        # however many times this is retried. Everything else — ingest,
        # assignment, sending, notifications — keeps working.
        await _tell_the_owners_once(tenant_id)
        log.warning("draft_skipped_budget", tenant_id=str(tenant_id), because=str(exc))


def _why_not(row: Any, message_id: UUID, *, forced: bool) -> str | None:
    """Six reasons not to spend a model call, cheapest first."""
    if row["status"] != "open":
        return "the conversation is closed"
    if row["channel_status"] != "connected":
        return "the channel is not connected"
    if not row["drafts_enabled"]:
        return "drafts are switched off for this workspace"
    if (row["consent"] or {}).get("opted_out_at"):
        return "the customer asked not to be messaged"
    # A regenerate is a person asking for a draft on purpose, so it skips the
    # two staleness checks and nothing else.
    if forced:
        return None
    if row["latest_inbound_id"] != message_id:
        return "a newer message has arrived"
    if row["answered_already"]:
        return "somebody has already replied"
    return None


async def _draft(tenant_id: UUID, conversation_id: UUID, message_id: UUID, run: Run) -> None:
    """The six steps of § 3, in order."""
    # 1 CLASSIFY
    async with tenant_session(tenant_id) as conn:
        tail = await conn.fetch(q.TAIL, conversation_id, CLASSIFY_TAIL)
    classified = await classify(
        tenant_id=tenant_id,
        run_id=run.id,
        conversation_tail=[(row["direction"], row["text"]) for row in tail],
    )
    run.cost_usd += classified.cost_usd
    read = classified.read

    if read.opt_out:
        # The ingest handler catches the exact phrases; this catches "please
        # don't send me anything else". Recorded, and no draft.
        await _record_opt_out(tenant_id, conversation_id)
        run.summary = "the customer asked not to be messaged"
        return

    # 2 GROUND
    ground = await grounding.load(tenant_id, conversation_id, read)
    if ground is None:
        return
    if read.intent in grounding.NEEDS_KNOWLEDGE:
        passages = await knowledge.search(tenant_id, _question(ground), run_id=run.id)
        ground = replace(ground, chunks=[_as_chunk(passage) for passage in passages])

    await _lead_if_they_are_shopping(tenant_id, ground, read)

    async with tenant_session(tenant_id) as conn, conn.transaction():
        await conn.execute(q.SUPERSEDE_LIVE, conversation_id)
        suggestion_id = await conn.fetchval(
            q.CLAIM, tenant_id, conversation_id, message_id, run.id, read.intent
        )

    # 3 DRAFT · 4 GUARDS · one regeneration
    drafted = await copilot.write(tenant_id=tenant_id, run_id=run.id, ground=ground, read=read)
    run.cost_usd += drafted.cost_usd
    findings = _inspect(drafted.draft, ground)
    regenerated = False
    if findings and drafted.draft is not None:
        regenerated = True
        drafted = await copilot.write(
            tenant_id=tenant_id,
            run_id=run.id,
            ground=ground,
            read=read,
            retry_because=[finding.message for finding in findings],
        )
        run.cost_usd += drafted.cost_usd
        findings = _inspect(drafted.draft, ground)

    if drafted.draft is None or findings:
        blocked = "; ".join(finding.message for finding in findings) or "no usable draft"
        async with tenant_session(tenant_id) as conn:
            await conn.execute(
                q.FINISH,
                suggestion_id,
                "blocked",
                None,
                None,
                None,
                None,
                [],
                [],
                None,
                blocked[:_MAX_ERROR],
            )
        run.summary = f"blocked: {blocked[:100]}"
        log.info("draft_blocked", conversation_id=str(conversation_id), because=blocked)
        return

    # 5 CONFIDENCE · 6 PERSIST
    draft = drafted.draft
    sources = _sources(draft, ground)
    band = confidence.band(
        read.intent,
        intent_confidence=read.confidence,
        needs_human=draft.needs_human,
        regenerated=regenerated,
        guards_passed_first_time=not regenerated,
        has_sources=bool(sources),
    )
    async with tenant_session(tenant_id) as conn:
        await conn.execute(
            q.FINISH,
            suggestion_id,
            "ready",
            draft.reply,
            _template(draft, ground),
            draft.language,
            band,
            sources,
            [action.model_dump() for action in draft.actions],
            draft.needs_human,
            None,
        )
    run.summary = f"{band} confidence {read.intent} draft"
    log.info("draft_ready", conversation_id=str(conversation_id), band=band, intent=read.intent)


def _inspect(draft: Draft | None, ground: Ground) -> Findings:
    """The six guards, on the exact text that would be sent.

    Against the database as `ground` found it seconds ago: the inventory guard
    reads statuses off the same rows the draft was written from, rather than
    off whatever the model remembers.
    """
    if draft is None:
        return []

    text = draft.reply or ""
    if draft.template_name:
        template = _find_template(ground, draft.template_name)
        if template is None:
            return [
                Finding("template", f"there is no approved template called {draft.template_name!r}")
            ]
        text = render_template(template["body"], draft.template_variables)
    elif not ground.window_open:
        return [Finding("window", "the 24-hour window is closed and this draft is free text")]

    # Only the cars the draft actually names. The inventory guard's "this
    # references no vehicle at all" is right for a marketing post and wrong for
    # a reply about shipping paperwork.
    named = {
        name: status for name, status in ground.vehicle_statuses().items() if _mentioned(name, text)
    }
    return [
        *price_guard.check(text, allowed=ground.allowed_prices()),
        *(inventory_guard.check(named) if named else []),
        *pii_guard.check_outbound(text, own_contacts=ground.own_contacts, notes=ground.notes),
        *brand_guard.check(text),
        *commitments_guard.check(text),
        *script_guard.check(text, customer_wrote=ground.customer_wrote),
    ]


def _mentioned(name: str, text: str) -> bool:
    """Does the reply name this car?

    Matched on the model rather than the whole string: "Land Cruiser" is what a
    customer writes, and "Toyota Land Cruiser 2023" is what the database calls
    it.
    """
    parts = name.split()
    if len(parts) < 2:
        return False
    model = " ".join(parts[1:-1]) if parts[-1].isdigit() else " ".join(parts[1:])
    return bool(model) and model.casefold() in text.casefold()


def _find_template(ground: Ground, name: str) -> dict[str, Any] | None:
    return next((row for row in ground.templates if row["name"] == name), None)


def _template(draft: Draft, ground: Ground) -> dict[str, Any] | None:
    if not draft.template_name:
        return None
    template = _find_template(ground, draft.template_name)
    if template is None:  # pragma: no cover - _inspect blocks this first
        return None
    return {
        "template_id": str(template["id"]),
        "name": template["name"],
        "variables": draft.template_variables,
    }


def _sources(draft: Draft, ground: Ground) -> list[dict[str, Any]]:
    """The chips under the draft: what it was built from, so it can be checked.

    Only what the model said it used, and only where we can still find the row
    — a chip that opens nothing is worse than no chip.
    """
    sources: list[dict[str, Any]] = []
    for vehicle_id in draft.used_vehicle_ids:
        row = next((v for v in ground.vehicles if str(v["id"]) == vehicle_id), None)
        if row is not None:
            sources.append(
                {
                    "kind": "vehicle",
                    "vehicle_id": str(row["id"]),
                    "label": f"{row['make']} {row['model']} {row['model_year'] or ''}".strip(),
                }
            )
    for chunk_id in draft.used_chunk_ids:
        passage = next((c for c in ground.chunks if c["chunk_id"] == chunk_id), None)
        if passage is not None:
            sources.append(
                {
                    "kind": "document",
                    "document_id": passage["document_id"],
                    "title": passage["title"],
                    "excerpt": passage["content"][:300],
                }
            )
    return sources


def _question(ground: Ground) -> str:
    """What to retrieve for: the customer's last message, in their own words."""
    inbound = [row["text"] for row in ground.tail if row["direction"] == "in" and row["text"]]
    return inbound[-1] if inbound else ""


def _as_chunk(passage: Passage) -> dict[str, Any]:
    return {
        "chunk_id": passage.chunk_id,
        "document_id": passage.document_id,
        "title": passage.title,
        "heading": passage.heading,
        "content": passage.content,
    }


async def _record_opt_out(tenant_id: UUID, conversation_id: UUID) -> None:
    async with tenant_session(tenant_id) as conn:
        await conn.execute(
            """update contacts set consent = consent || jsonb_build_object('opted_out_at', $2::text)
                where id = (select contact_id from conversations where id = $1)""",
            conversation_id,
            datetime.now(UTC).isoformat(),
        )


async def _lead_if_they_are_shopping(tenant_id: UUID, ground: Ground, read: Read) -> None:
    """A customer asking a buying question has a lead, whether or not anybody
    pressed a button (docs/sales/04-ai-copilot.md § 5)."""
    if read.intent not in BUYING:
        return
    # Only when there is no doubt which car. Two candidates and a guess is a
    # lead about the wrong one, which is worse than no lead.
    vehicle_id = ground.vehicles[0]["id"] if len(ground.vehicles) == 1 else None
    context = ground.context
    profile = context["profile"] or {}
    exporting = (profile.get("purchase_type") or {}).get(
        "value"
    ) == "export" or read.intent == "export_shipping"

    async with tenant_session(tenant_id) as conn, conn.transaction():
        if await conn.fetchval(q.OPEN_LEAD_EXISTS, context["contact_id"], vehicle_id):
            return
        board = await conn.fetchrow(q.BOARD_FOR, tenant_id, exporting)
        if board is None:
            log.warning("no_board_for_an_automatic_lead", tenant_id=str(tenant_id))
            return
        from_ad = await conn.fetchval(q.CAME_FROM_AN_AD, context["conversation_id"])
        lead_id = await conn.fetchval(
            """insert into leads (tenant_id, contact_id, conversation_id, pipeline_id, stage_id,
                                  stage_entered_at, owner_id, team_id, vehicle_id, source)
               select $1, $2, $3, $4, $5, now(), ct.owner_id, ct.team_id, $6, $7
                 from contacts ct where ct.id = $2
               returning id""",
            tenant_id,
            context["contact_id"],
            context["conversation_id"],
            board["pipeline_id"],
            board["stage_id"],
            vehicle_id,
            "ad" if from_ad else "whatsapp",
        )
        await event_line(
            conn,
            tenant_id,
            context["conversation_id"],
            "lead_created",
            "Lead created from this conversation",
            lead_id=str(lead_id),
        )
    log.info("lead_created_automatically", lead_id=str(lead_id), intent=read.intent)


async def _tell_the_owners_once(tenant_id: UUID) -> None:
    """Once a day, not once a message.

    A workspace at its ceiling receives dozens of messages before anybody
    notices, and a notification per message is how the bell becomes the first
    thing people stop opening.
    """
    today = datetime.now(UTC).date().isoformat()
    async with tenant_session(tenant_id) as conn, conn.transaction():
        for row in await conn.fetch(
            "select user_id from memberships where tenant_id = $1 and role in ('owner', 'admin')",
            tenant_id,
        ):
            await notify(
                conn,
                tenant_id=tenant_id,
                user_id=row["user_id"],
                kind="ai_budget_exhausted",
                title="The AI assistant has paused for this month",
                body="Drafts and profile updates have stopped. Everything else is unaffected.",
                entity={"type": "tenant", "id": str(tenant_id)},
                dedupe_key=f"budget:{tenant_id}:{today}",
            )


@handler("conversation.idle")
async def on_conversation_idle(event: Event) -> None:
    """Placeholder until Task 10.

    Here rather than in parked.py because this module now owns the type, and
    `bus.register` refuses a second handler for one type — which is exactly the
    check that stops a placeholder outliving its replacement.
    """
    log.info("conversation_idle_not_handled_yet", payload=event.payload)
