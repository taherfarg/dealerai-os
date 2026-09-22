"""Everything the copilot does when nobody asked it to.

One handler per event: a document was uploaded, a customer wrote, a
conversation went quiet, an hour passed.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import structlog

from ...agents.sales import copilot
from ...agents.sales import followup as followup_agent
from ...agents.sales.copilot import Draft
from ...agents.sales.intent import Read, classify
from ...agents.sales.profile import PROPOSABLE, Learned, coerce, study
from ...ai.embeddings import embed, literal
from ...ai.gateway import assert_within_budget
from ...core.errors import BudgetExceeded, Unusable
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
from ...sales import confidence, followups, grounding, knowledge, scoring
from ...sales import profile as profile_fields
from ...sales.grounding import Ground
from ...sales.knowledge import Passage, chunk, embeddable, extract
from ...sales.messaging import render_template, variable_numbers, window_is_open
from ...sales.runs import Run, agent_run
from ...sales.settings import SalesSettings
from ...sales.timeline import event_line
from ..bus import Event, emit, handler
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


# ---------------------------------------------------------------------------
# What a quiet conversation taught us — docs/sales/04-ai-copilot.md § 4, § 5
# ---------------------------------------------------------------------------

#: Below this there is nothing new to learn and a model call is waste. At
#: Pollux's volume this one decision is a couple of thousand calls a month.
MIN_NEW_MESSAGES = 2

#: How much of the conversation the profile agent reads.
STUDY_TAIL = 60


@handler("conversation.idle")
async def on_conversation_idle(event: Event) -> None:
    """Fifteen minutes of quiet: write down what we learned."""
    if event.tenant_id is None:
        raise ValueError("conversation.idle requires a tenant")
    tenant_id = event.tenant_id
    conversation_id = UUID(str(event.payload["conversation_id"]))
    message_id = UUID(str(event.payload["message_id"]))

    async with tenant_session(tenant_id) as conn:
        state = await conn.fetchrow(q.IDLE_STATE, conversation_id, message_id)
        if state is None:
            return
        if state["newer_inbound"]:
            return  # they are still writing; a later idle event will do this
        if state["new_since_cursor"] < MIN_NEW_MESSAGES:
            return
        tail = await conn.fetch(q.TAIL, conversation_id, STUDY_TAIL)
        leads = await conn.fetch(q.OPEN_LEADS, state["contact_id"])
    if not tail:
        return

    try:
        await assert_within_budget(tenant_id)
    except BudgetExceeded:
        await _tell_the_owners_once(tenant_id)
        return

    async with agent_run(
        tenant_id,
        goal="learn from a conversation",
        goal_input={"conversation_id": str(conversation_id)},
    ) as run:
        studied = await study(
            tenant_id=tenant_id,
            run_id=run.id,
            transcript=_transcript(tail),
            profile_now=_profile_lines(state["profile"]),
            leads_now=_lead_lines(leads),
        )
        run.cost_usd += studied.cost_usd
        await _write_down(
            tenant_id,
            conversation_id,
            contact_id=state["contact_id"],
            learned=studied.learned,
            ours={str(row["id"]) for row in tail},
            cursor=tail[-1]["id"],
            run=run,
        )


def _transcript(tail: list[Any]) -> str:
    """The conversation with its message ids, because evidence is the point."""
    return "\n".join(
        f"[{row['id']}] {'CUSTOMER' if row['direction'] == 'in' else 'US'}: {row['text']}"
        for row in tail
    )


def _profile_lines(profile: dict[str, Any] | None) -> str:
    return "\n".join(
        f"- {key}: {value.get('value')} (set by {value.get('source')})"
        for key, value in sorted((profile or {}).items())
        if isinstance(value, dict)
    )


def _lead_lines(leads: list[Any]) -> str:
    return "\n".join(
        f"- {row['pipeline']} · {row['stage']} · "
        f"{(str(row['make'] or '') + ' ' + str(row['model'] or '')).strip() or 'no car yet'}"
        for row in leads
    )


async def _write_down(
    tenant_id: UUID,
    conversation_id: UUID,
    *,
    contact_id: UUID,
    learned: Learned,
    ours: set[str],
    cursor: UUID,
    run: Run,
) -> None:
    """What is kept, and what is dropped. This is the half that is not a model.

    Three filters, and a field failing any of them costs that field rather than
    the run: one bad country code must not take the summary with it.
    """
    now = datetime.now(UTC)
    changes: list[tuple[str, Any, str]] = []
    for update in learned.updates:
        if update.evidence_message_id not in ours:
            # The grounding check. A message id from another thread would put
            # somebody else's words on this customer's record.
            log.info("profile_update_ungrounded", field=update.field)
            continue
        try:
            value = profile_fields.check(update.field, coerce(update.field, update.value))
        except Unusable as exc:
            log.info("profile_update_invalid", field=update.field, why=str(exc))
            continue
        changes.append((update.field, value, update.evidence_message_id))

    # An unknown signal is worth nothing to the scorer already. Dropping it here
    # keeps it out of the stored list too, so the drawer's reasons and the
    # number above them cannot disagree.
    signals = [
        {"signal": seen.signal, "evidence_message_id": seen.evidence_message_id}
        for seen in learned.signals
        if seen.signal in PROPOSABLE and seen.evidence_message_id in ours
    ]

    async with tenant_session(tenant_id) as conn, conn.transaction():
        for field, value, evidence in changes:
            # One field at a time, so one evidence id belongs to one field.
            # `apply` is what refuses to overwrite a person's answer.
            current = await conn.fetchval("select profile from contacts where id = $1", contact_id)
            await conn.execute(
                "update contacts set profile = $2::jsonb, profile_updated_at = $3 where id = $1",
                contact_id,
                profile_fields.apply(
                    current or {},
                    {field: value},
                    source="ai",
                    now=now,
                    evidence_message_id=evidence,
                ),
                now,
            )

        await conn.execute(
            "update conversations set summary = $2::jsonb where id = $1",
            conversation_id,
            {
                "text": learned.summary.text,
                "next_action": learned.summary.next_action,
                "cursor_message_id": str(cursor),
                "at": now.isoformat(),
            },
        )

        weights = SalesSettings.model_validate(
            await conn.fetchval("select sales_settings from tenants where id = $1", tenant_id) or {}
        ).scoring_weights
        for lead in await conn.fetch(q.LEADS_TO_RESCORE, contact_id):
            await _rescore(conn, lead, signals, weights, now)

    run.summary = learned.summary.next_action or "nothing new"
    log.info(
        "conversation_studied",
        conversation_id=str(conversation_id),
        fields=[field for field, _, _ in changes],
        signals=[signal["signal"] for signal in signals],
    )


async def _rescore(
    conn: Any, lead: Any, signals: list[dict[str, Any]], weights: dict[str, int], now: datetime
) -> None:
    """Stored signals plus the two code can see, through the same pure function
    the drawer's reasons come from (sales/scoring.py).

    Keyed by name, so a second run does not count `asked_price` twice — and the
    newer evidence wins, which is the one the salesperson would rather open.
    """
    stored = {row["signal"]: row for row in (lead["score_signals"] or [])}
    stored.update({row["signal"]: row for row in signals})
    merged = scoring.from_stored(list(stored.values()))

    pace = (
        await conn.fetch(q.REPLY_PACE, lead["conversation_id"]) if lead["conversation_id"] else []
    )
    observed = scoring.observed_signals(
        inbound_at=[row["created_at"] for row in pace],
        reply_latencies=[row["latency"] for row in pace if row["latency"] is not None],
        now=now,
    )
    total, band, _ = scoring.score(merged + observed, weights)

    await conn.execute(
        "update leads set score = $2, intent_band = $3, score_signals = $4::jsonb where id = $1",
        lead["id"],
        total,
        band,
        [
            {"signal": signal.name, "evidence_message_id": signal.evidence_message_id}
            for signal in merged
        ],
    )
    if band == "hot" and lead["intent_band"] != "hot" and lead["owner_id"]:
        # The one notification this agent sends. A lead going cold is not news;
        # a lead going hot is somebody's afternoon.
        await notify(
            conn,
            tenant_id=lead["tenant_id"],
            user_id=lead["owner_id"],
            kind="lead_hot",
            title=f"{lead['full_name'] or 'A customer'} is now a hot lead",
            entity={"type": "lead", "id": str(lead["id"])},
            dedupe_key=f"hot:{lead['id']}",
        )


# ---------------------------------------------------------------------------
# Follow-ups — docs/sales/04-ai-copilot.md § 6
# ---------------------------------------------------------------------------

#: Which approved template carries which reason, best first, when the 24-hour
#: window has closed.
TEMPLATES_FOR: dict[str, list[str]] = {
    "price_drop": ["price_update", "vehicle_available"],
    "similar_arrival": ["vehicle_available", "price_update"],
    "no_reply_48h": ["vehicle_available"],
}

#: How long a customer may say nothing before a reply is worth chasing
#: (docs/sales/04-ai-copilot.md § 6).
NO_REPLY_AFTER = timedelta(hours=48)


async def schedule_no_reply_check(
    conn: Any, tenant_id: UUID, conversation_id: UUID, now: datetime
) -> None:
    """We replied; look again in two days.

    Scheduled by the message that starts the wait, exactly as the response
    target is (events/handlers/inbox.py). The spec asks for an hourly sweep,
    and a sweep cannot work here: `system_session` has no tenant context and
    under RLS sees nothing tenant-owned, so there is no query that enumerates
    dealerships from a worker. Scheduling per conversation needs no
    enumeration, no scheduler process, and is exact rather than up to an hour
    late — and it inherits the queue's lock, retry and dead-letter.

    Deduped per conversation per day, so a thread with six replies in it
    schedules one check.
    """
    when = now + NO_REPLY_AFTER
    await emit(
        conn,
        "followup.check",
        {"trigger": "no_reply_48h", "conversation_id": str(conversation_id)},
        tenant_id=tenant_id,
        dedupe_key=f"followup:{conversation_id}:{when:%Y%m%d}",
        run_after=when,
        priority=2,
    )


@handler("followup.check")
async def on_followup_check(event: Event) -> None:
    """One lead, named directly or through the conversation we last replied in."""
    if event.tenant_id is None:
        raise ValueError("followup.check requires a tenant")
    trigger = str(event.payload.get("trigger") or "no_reply_48h")
    lead_id = event.payload.get("lead_id")
    if lead_id is None:
        async with tenant_session(event.tenant_id) as conn:
            lead_id = await conn.fetchval(
                q.LEAD_FOR_CONVERSATION, UUID(str(event.payload["conversation_id"]))
            )
        if lead_id is None:
            return  # no open lead: nothing to follow up on
    await _consider(event.tenant_id, UUID(str(lead_id)), trigger)


@handler("vehicle.price_changed")
async def on_price_changed(event: Event) -> None:
    """A price that went *down* is news. One that went up is not."""
    if event.tenant_id is None:
        raise ValueError("vehicle.price_changed requires a tenant")
    before = event.payload.get("before_minor")
    after = event.payload.get("after_minor")
    if before is None or after is None or int(after) >= int(before):
        return
    vehicle_id = UUID(str(event.payload["vehicle_id"]))
    async with tenant_session(event.tenant_id) as conn, conn.transaction():
        for lead in await conn.fetch(q.LEADS_ON_VEHICLE, vehicle_id):
            await emit(
                conn,
                "followup.check",
                {"trigger": "price_drop", "lead_id": str(lead["id"])},
                tenant_id=event.tenant_id,
                dedupe_key=f"followup:{lead['id']}:price:{after}",
                priority=2,
            )


async def offer_a_new_arrival(conn: Any, tenant_id: UUID, vehicle_id: UUID) -> None:
    """Called from the vehicle.created handler, which already holds a connection.

    A second handler for `vehicle.created` is impossible — bus.register refuses
    one — so this is a function rather than a handler, and inventory.py calls it
    where it already knows the car is ready.
    """
    car = await conn.fetchrow("select make, model, status from vehicles where id = $1", vehicle_id)
    if car is None or car["status"] != "available":
        return
    for lead in await conn.fetch(q.LEADS_WANTING, tenant_id, car["model"]):
        await emit(
            conn,
            "followup.check",
            {
                "trigger": "similar_arrival",
                "lead_id": str(lead["id"]),
                "vehicle_id": str(vehicle_id),
            },
            tenant_id=tenant_id,
            dedupe_key=f"followup:{lead['id']}:arrival:{vehicle_id}",
            priority=2,
        )


async def _consider(tenant_id: UUID, lead_id: UUID, trigger: str) -> None:
    """Eligibility in code, then — only then — ask whether there is anything to say."""
    now = datetime.now(UTC)
    async with tenant_session(tenant_id) as conn:
        lead = await conn.fetchrow(q.FOLLOWUP_STATE, lead_id)
    if lead is None or lead["category"] != "open":
        return

    if trigger == "no_reply_48h" and lead["last_direction"] != "out":
        # They wrote back. Answering that is a person's job and the response
        # target's, not a follow-up.
        log.info("followup_skipped", lead_id=str(lead_id), because="the customer replied")
        return

    settings = SalesSettings.model_validate(lead["sales_settings"] or {})
    verdict = followups.may_follow_up(
        lead, trigger=trigger, now=now, settings=settings, tz=ZoneInfo(lead["timezone"])
    )
    if not verdict.allowed:
        if verdict.retry_at is not None:
            async with tenant_session(tenant_id) as conn:
                await emit(
                    conn,
                    "followup.check",
                    {"trigger": trigger, "lead_id": str(lead_id)},
                    tenant_id=tenant_id,
                    dedupe_key=f"followup:{lead_id}:{verdict.retry_at:%Y%m%d%H}",
                    run_after=verdict.retry_at,
                    priority=2,
                )
        log.info("followup_skipped", lead_id=str(lead_id), because=verdict.because)
        return

    try:
        await assert_within_budget(tenant_id)
    except BudgetExceeded:
        await _tell_the_owners_once(tenant_id)
        return

    async with agent_run(
        tenant_id,
        goal="consider a follow-up",
        goal_input={"lead_id": str(lead_id), "trigger": trigger},
    ) as run:
        async with tenant_session(tenant_id) as conn:
            tail = await conn.fetch(q.FOLLOWUP_TAIL, lead["conversation_id"])
        considered = await followup_agent.consider(
            tenant_id=tenant_id,
            run_id=run.id,
            trigger=trigger,
            context=_followup_context(lead, tail),
        )
        run.cost_usd += considered.cost_usd
        written = considered.written

        if written is None or not written.genuine_reason:
            # The whole point. Nobody is interrupted and the cadence decides
            # when to look again.
            run.summary = "nothing new to say"
            log.info("followup_declined", lead_id=str(lead_id), trigger=trigger)
            return

        findings = _inspect_followup(written.draft, lead, tail)
        if findings:
            run.summary = "; ".join(finding.message for finding in findings)[:200]
            log.info("followup_blocked", lead_id=str(lead_id), because=run.summary)
            return

        await _raise_the_task(tenant_id, lead, written, trigger, now, settings)
        run.summary = written.reason


def _followup_context(lead: Any, tail: list[Any]) -> str:
    currency = lead["tenant_currency"] or "AED"
    car = f"{lead['make'] or ''} {lead['model'] or ''} {lead['model_year'] or ''}".strip()
    lines = [
        "## The lead",
        f"- customer: {lead['full_name'] or 'unknown'} ({lead['country'] or '??'})",
        f"- board: {lead['pipeline']} · {lead['stage']}",
        f"- car: {car or 'none chosen yet'}",
    ]
    if lead["price_minor"] is not None:
        lines.append(f"- price now: {grounding.money(lead['price_minor'], currency)}")
    if lead["budget_minor"] is not None:
        lines.append(f"- their budget: {grounding.money(lead['budget_minor'], currency)}")
    conversation = "\n".join(
        f"{'CUSTOMER' if row['direction'] == 'in' else 'US'}: {row['text']}" for row in tail
    )
    return (
        "\n".join(lines)
        + f"\n\n## The conversation so far\n<untrusted>\n{conversation}\n</untrusted>"
    )


def _inspect_followup(draft: str, lead: Any, tail: list[Any]) -> Findings:
    """The guards that apply to a message with no thread in front of it.

    Narrower than the draft loop's: there is no window state to check here (the
    task decides that when it is sent) and no inventory beyond the one car,
    which the eligibility rules already confirmed is available.
    """
    allowed = {
        Decimal(value) / 100
        for value in (lead["price_minor"], lead["budget_minor"])
        if value is not None
    }
    customer_wrote = " ".join(row["text"] for row in tail if row["direction"] == "in")
    return [
        *price_guard.check(draft, allowed=allowed),
        *commitments_guard.check(draft),
        *brand_guard.check(draft),
        *script_guard.check(draft, customer_wrote=customer_wrote),
    ]


async def _raise_the_task(
    tenant_id: UUID,
    lead: Any,
    written: Any,
    trigger: str,
    now: datetime,
    settings: SalesSettings,
) -> None:
    """The output is a task for the lead's owner, never a message."""
    window_open = window_is_open(lead["wa_window_expires_at"], now)
    draft: dict[str, Any] = {"reason": written.reason, "text": None}
    if window_open:
        draft["text"] = written.draft
    else:
        async with tenant_session(tenant_id) as conn:
            template = await conn.fetchrow(
                q.TEMPLATE_BY_NAME, lead["channel_id"], TEMPLATES_FOR.get(trigger, [])
            )
        if template is not None:
            draft["template_id"] = str(template["id"])
            draft["template_name"] = template["name"]
            draft["variables"] = _variables(template, lead)
        # No suitable approved template: a task with no draft. "Call the
        # customer" is worth more than a message that cannot be sent.

    async with tenant_session(tenant_id) as conn, conn.transaction():
        task_id = await conn.fetchval(
            """insert into tasks (tenant_id, title, kind, due_at, assignee_id, contact_id,
                                  lead_id, conversation_id, source, ai_draft)
               values ($1,$2,'follow_up',$3,$4,$5,$6,$7,'ai',$8::jsonb) returning id""",
            tenant_id,
            written.reason[:120],
            now,
            lead["owner_id"],
            lead["contact_id"],
            lead["id"],
            lead["conversation_id"],
            draft,
        )
        if lead["owner_id"]:
            await notify(
                conn,
                tenant_id=tenant_id,
                user_id=lead["owner_id"],
                kind="followup_ready",
                title=written.reason[:120],
                body=lead["full_name"],
                entity={"type": "task", "id": str(task_id)},
                dedupe_key=f"followup:{task_id}",
            )
    log.info("followup_raised", lead_id=str(lead["id"]), task_id=str(task_id), trigger=trigger)


def _variables(template: Any, lead: Any) -> list[str]:
    """Fill {{1}}, {{2}}… from what we know, in order.

    Names, then the car, then the price — the order every utility template in
    this account uses. A template wanting something else gets blanks, which is
    visible in the card rather than wrong on the customer's phone.
    """
    currency = lead["tenant_currency"] or "AED"
    known = [
        (lead["full_name"] or "").split()[0] if lead["full_name"] else "",
        f"{lead['make'] or ''} {lead['model'] or ''}".strip(),
        grounding.money(lead["price_minor"], currency) if lead["price_minor"] else "",
    ]
    wanted = variable_numbers(template["body"])
    return [known[index - 1] if index <= len(known) else "" for index in wanted]
