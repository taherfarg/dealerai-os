"""The copilot's SQL. One module, so a change to what a draft may see is one diff.

None of these take a user. The worker has no session user, and a draft is
grounded in the conversation it answers rather than in what any particular
salesperson happens to be allowed to see.
"""

from __future__ import annotations

#: The conversation, its customer, and the state that decides what may be sent.
CONTEXT = """
select cv.id as conversation_id, cv.status, cv.wa_window_expires_at, cv.summary,
       cv.channel_id, cv.assigned_to, cv.owner_id,
       ch.status as channel_status,
       ct.id as contact_id, ct.full_name, ct.locale, ct.country, ct.profile, ct.consent,
       t.name as tenant_name, t.currency, t.timezone, t.sales_settings
  from conversations cv
  join contacts ct on ct.id = cv.contact_id
  -- Left, because `conversations.channel_id` is nullable and an inner join
  -- would make a conversation with no channel indistinguishable from one that
  -- does not exist. It reads back as a channel that is not connected, which is
  -- what the draft preconditions already refuse on.
  left join channels ch on ch.id = cv.channel_id
  join tenants t on t.id = cv.tenant_id
 where cv.id = $1
"""

#: The last N messages, oldest first, with a voice note's transcript standing in
#: for its body.
#:
#: `kind = 'message'` excludes the grey event lines ("Assigned to Ahmed") and
#: the internal notes. An event line reads to a model as something the customer
#: can see, and a note is loaded separately because it has to be labelled
#: differently in the prompt.
TAIL = """
select id, direction, origin, type,
       coalesce(nullif(body, ''), transcript->>'text', '') as text,
       created_at
  from (
    select * from messages
     where conversation_id = $1 and kind = 'message'
     order by created_at desc limit $2
  ) recent
 order by created_at
"""

#: What the team said about this customer to each other. Five is enough to carry
#: the thread of a handover without turning the prompt into a second inbox.
NOTES = """
select body, created_at from messages
 where conversation_id = $1 and kind = 'note' and body is not null
 order by created_at desc limit 5
"""

#: Open leads and the car each one is about — the difference between "a customer"
#: and "the customer who has been negotiating the white Land Cruiser for a week".
OPEN_LEADS = """
select l.id, l.tenant_id, l.contact_id, l.conversation_id, l.owner_id, l.budget_minor,
       l.currency, l.score, l.intent_band, l.score_signals, l.vehicle_id,
       s.name as stage, p.name as pipeline,
       v.make, v.model, v.model_year, v.price_minor, v.status as vehicle_status,
       ct.full_name, ct.consent
  from leads l
  join pipeline_stages s on s.id = l.stage_id
  join pipelines p on p.id = l.pipeline_id
  join contacts ct on ct.id = l.contact_id
  left join vehicles v on v.id = l.vehicle_id
 where l.contact_id = $1 and s.category = 'open'
 order by l.created_at desc limit 5
"""

#: Cars that match what the customer just described.
#:
#: `available` and `reserved` both come back on purpose: a reserved car the
#: customer is asking about must be describable as reserved, and a model that
#: cannot see it will say it does not exist.
MATCHING_VEHICLES = """
select id, make, model, trim, model_year, vehicle_condition, mileage_km, price_minor,
       currency, exterior_color, interior_color, engine, transmission, fuel, seats,
       features, status, steering, target_markets
  from vehicles
 where tenant_id = $1
   and status in ('available', 'reserved')
   and ($2::text is null or make ilike '%' || $2 || '%')
   and ($3::text is null or model ilike '%' || $3 || '%')
   and ($4::int is null or model_year = $4)
 order by (status = 'available') desc, listed_at desc
 limit 6
"""

#: The fallback when the customer named no car at all: what this dealership is
#: actually holding, newest first. Without it a greeting gets a draft that
#: cannot name a single thing for sale.
RECENT_VEHICLES = """
select id, make, model, trim, model_year, vehicle_condition, mileage_km, price_minor,
       currency, exterior_color, interior_color, engine, transmission, fuel, seats,
       features, status, steering, target_markets
  from vehicles
 where tenant_id = $1 and status = 'available'
 order by listed_at desc limit 4
"""

#: The templates a closed window leaves available, with their variables.
APPROVED_TEMPLATES = """
select id, name, language, category, body, variables
  from message_templates
 where channel_id = $1 and status = 'approved'
 order by category, name
"""

#: The dealership's own numbers, so the PII guard can tell them from a
#: stranger's. `handle` is where a WhatsApp channel keeps its display number.
OWN_CONTACTS = """
select handle as phone from channels
 where tenant_id = $1 and platform = 'whatsapp' and handle is not null
"""

#: Hybrid retrieval, fused by reciprocal rank (docs/sales/04-ai-copilot.md § 7).
#:
#: RRF rather than a weighted sum of scores: cosine distance and ts_rank_cd are
#: not on the same scale and never will be, so any weighting is a constant
#: somebody has to tune per tenant. Ranks are comparable by construction, and
#: k = 60 is the value from the original paper that nobody has needed to move.
#:
#: Both halves are pre-filtered by tenant and by `status = 'ready'`: a document
#: still processing has chunks with no embedding, and a withdrawn one must stop
#: being quoted the moment it is deleted.
SEARCH_KNOWLEDGE = """
with vector_hits as (
  select c.id, row_number() over (order by c.embedding <=> $2::vector) as rank
    from doc_chunks c join documents d on d.id = c.document_id
   where c.tenant_id = $1 and d.status = 'ready' and c.embedding is not null
   order by c.embedding <=> $2::vector
   limit $4
),
text_hits as (
  select c.id,
         row_number() over (
           order by ts_rank_cd(to_tsvector('simple', c.content), q) desc
         ) as rank
    from doc_chunks c
    join documents d on d.id = c.document_id,
         websearch_to_tsquery('simple', $3) q
   where c.tenant_id = $1 and d.status = 'ready'
     and to_tsvector('simple', c.content) @@ q
   limit $4
),
fused as (
  select id, sum(1.0 / (60 + rank)) as score
    from (select * from vector_hits union all select * from text_hits) hits
   group by id
)
select c.id, c.document_id, c.content, c.meta->>'heading' as heading,
       d.title, d.kind, fused.score::float8 as score
  from fused
  join doc_chunks c on c.id = fused.id
  join documents d on d.id = c.document_id
 order by fused.score desc, c.id
 limit $5
"""

#: $1 the chunk ids a draft says it used. What search_knowledge found reaches
#: the model through the tool, not through the ground the handler holds.
CITED_PASSAGES = """
select c.id as chunk_id, c.document_id::text as document_id, coalesce(d.title, '') as title,
       coalesce(c.meta->>'heading', '') as heading, c.content
  from doc_chunks c join documents d on d.id = c.document_id
 where c.id = any($1::bigint[]) and d.status = 'ready'
"""

# ---------------------------------------------------------------------------
# The draft loop
# ---------------------------------------------------------------------------

#: Everything that decides whether to draft at all, in one read.
#:
#: Six `if` statements over six queries is six chances for the state to move
#: underneath them. This returns the facts; the handler reads them in the order
#: docs/sales/04-ai-copilot.md § 3 states.
DRAFT_PRECONDITIONS = """
select cv.status, cv.wa_window_expires_at,
       ch.status as channel_status,
       ct.consent,
       coalesce((t.sales_settings->>'drafts_enabled')::boolean, true) as drafts_enabled,
       (select m.id from messages m
         where m.conversation_id = cv.id and m.kind = 'message' and m.direction = 'in'
         order by m.created_at desc limit 1) as latest_inbound_id,
       exists (
         select 1 from messages m
          where m.conversation_id = cv.id and m.kind = 'message' and m.direction = 'out'
            and m.created_at > (select created_at from messages where id = $2)
       ) as answered_already
  from conversations cv
  left join channels ch on ch.id = cv.channel_id
  join contacts ct on ct.id = cv.contact_id
  join tenants t on t.id = cv.tenant_id
 where cv.id = $1
"""

#: A `generating` row whose worker died would otherwise block this conversation
#: for ever, because of the partial unique index. Five minutes is thirty times
#: the p95 the latency gate allows.
RELEASE_STALE = """
update ai_suggestions set status = 'superseded'
 where conversation_id = $1 and status = 'generating'
   and created_at < now() - interval '5 minutes'
"""

#: Supersede whatever is live, then claim the slot — one statement each, inside
#: one transaction. The partial unique index then makes two workers drafting
#: the same conversation impossible rather than merely unlikely.
SUPERSEDE_LIVE = """
update ai_suggestions set status = 'superseded'
 where conversation_id = $1 and status in ('generating', 'ready')
"""

CLAIM = """
insert into ai_suggestions (tenant_id, conversation_id, for_message_id, run_id, status, intent)
values ($1, $2, $3, $4, 'generating', $5)
returning id
"""

FINISH = """
update ai_suggestions set
    status = $2, text = $3, template = $4::jsonb, language = $5, confidence = $6,
    sources = $7::jsonb, actions = $8::jsonb, needs_human = $9, blocked_reason = $10
 where id = $1
"""

#: Does this customer already have an open lead — on this car, or on no car at
#: all? Either one means we are not starting a second.
OPEN_LEAD_EXISTS = """
select exists (
  select 1 from leads l join pipeline_stages s on s.id = l.stage_id
   where l.contact_id = $1 and s.category = 'open'
     and ($2::uuid is null or l.vehicle_id = $2 or l.vehicle_id is null)
)
"""

#: Where an automatic lead lands: the Export board when the customer is
#: exporting, otherwise the default one, and its first open stage.
BOARD_FOR = """
select p.id as pipeline_id, s.id as stage_id
  from pipelines p
  join pipeline_stages s on s.pipeline_id = p.id and s.category = 'open'
 where p.tenant_id = $1
 order by ($2::boolean and p.name ilike '%export%') desc, p.is_default desc, p.position,
          s.position
 limit 1
"""

#: A Click-to-WhatsApp referral on the conversation's first message is what
#: makes a lead's source `ad` rather than `whatsapp`.
CAME_FROM_AN_AD = """
select exists (
  select 1 from messages where conversation_id = $1 and referral is not null
)
"""

# ---------------------------------------------------------------------------
# The draft over HTTP
# ---------------------------------------------------------------------------

#: What the composer shows. A superseded draft is not live and is not shown; a
#: blocked one is, as one muted line, because a salesperson who sees nothing
#: assumes the AI is broken and one who reads the reason learns what it will
#: not do.
LIVE_SUGGESTION = """
select id, conversation_id, for_message_id, status, text, template, language, confidence,
       intent, sources, actions, needs_human, blocked_reason, created_at
  from ai_suggestions
 where conversation_id = $1 and status in ('generating', 'ready', 'blocked')
   and outcome is null
 order by created_at desc limit 1
"""

LATEST_INBOUND = """
select id from messages
 where conversation_id = $1 and kind = 'message' and direction = 'in'
 order by created_at desc limit 1
"""

#: `outcome is null` in the WHERE is what makes an outcome final: recording a
#: second one would move the acceptance metric after the fact.
#:
#: The status leaves the live set whatever the outcome was — `superseded` here
#: means "no longer the draft on screen", and what ended it is `outcome`. It
#: has to leave: the partial unique index is what allows the next draft to
#: claim the conversation.
RECORD_OUTCOME = """
update ai_suggestions set outcome = $2, outcome_at = now(), outcome_by = $3,
       edit_ratio = $4, discard_reason = $5, final_message_id = $6, status = 'superseded'
 where id = $1 and outcome is null
returning id
"""

# ---------------------------------------------------------------------------
# What a quiet conversation taught us
# ---------------------------------------------------------------------------

#: Is there anything to learn, and has the customer written since?
#:
#: The cursor lives in `conversations.summary` rather than in a column of its
#: own, because it is written every time a summary is, by definition — and a
#: cursor that can fall out of step with the summary it belongs to is a cursor
#: that will.
IDLE_STATE = """
select cv.contact_id, ct.profile, cv.summary,
       (select count(*) from messages m
         where m.conversation_id = cv.id and m.kind = 'message' and m.direction = 'in'
           and (cv.summary->>'cursor_message_id' is null
                or m.created_at > (select created_at from messages
                                    where id = (cv.summary->>'cursor_message_id')::uuid))
       ) as new_since_cursor,
       (select count(*) from messages m
         where m.conversation_id = cv.id and m.kind = 'message' and m.direction = 'in'
           and m.created_at > (select created_at from messages where id = $2)
       ) as newer_inbound
  from conversations cv join contacts ct on ct.id = cv.contact_id
 where cv.id = $1
"""

#: When the customer wrote, and how long we took to answer. Both signals code
#: can see for itself: pace, and silence.
REPLY_PACE = """
select m.created_at,
       (select min(reply.created_at) from messages reply
         where reply.conversation_id = m.conversation_id and reply.kind = 'message'
           and reply.direction = 'out' and reply.created_at > m.created_at
       ) - m.created_at as latency
  from messages m
 where m.conversation_id = $1 and m.kind = 'message' and m.direction = 'in'
 order by m.created_at desc limit 5
"""

#: The leads a conversation's customer has open, with what a notification needs.
LEADS_TO_RESCORE = """
select l.id, l.tenant_id, l.owner_id, l.score_signals, l.intent_band, l.conversation_id,
       ct.full_name
  from leads l
  join pipeline_stages s on s.id = l.stage_id
  join contacts ct on ct.id = l.contact_id
 where l.contact_id = $1 and s.category = 'open'
"""

# ---------------------------------------------------------------------------
# Follow-ups — docs/sales/04-ai-copilot.md § 6
# ---------------------------------------------------------------------------

#: Everything the eligibility rules need, in one read.
FOLLOWUP_STATE = """
select l.id, l.tenant_id, l.contact_id, l.conversation_id, l.owner_id, l.vehicle_id,
       l.budget_minor, l.currency, l.created_at as lead_created_at,
       ct.full_name, ct.locale, ct.country, ct.consent, ct.profile,
       s.name as stage, p.name as pipeline, s.category,
       v.make, v.model, v.model_year, v.price_minor, v.status as vehicle_status,
       cv.wa_window_expires_at, cv.channel_id,
       t.timezone, t.currency as tenant_currency, t.sales_settings,
       (select count(*) from tasks k
         where k.lead_id = l.id and k.source = 'ai' and k.kind = 'follow_up'
       ) as ai_followups,
       (select max(k.created_at) from tasks k
         where k.lead_id = l.id and k.source = 'ai' and k.kind = 'follow_up'
       ) as last_followup_at,
       exists (
         select 1 from tasks k
          where k.lead_id = l.id and k.source = 'ai' and k.kind = 'follow_up'
            and k.status = 'open'
       ) as open_ai_task,
       -- Ours was the last word. A customer who has written and is waiting is
       -- the inbox's problem, not the follow-up agent's.
       (select m.direction from messages m
         where m.conversation_id = l.conversation_id and m.kind = 'message'
         order by m.created_at desc limit 1) as last_direction
  from leads l
  join pipeline_stages s on s.id = l.stage_id
  join pipelines p on p.id = l.pipeline_id
  join contacts ct on ct.id = l.contact_id
  join tenants t on t.id = l.tenant_id
  left join vehicles v on v.id = l.vehicle_id
  left join conversations cv on cv.id = l.conversation_id
 where l.id = $1
"""

#: Leads on one car, for a price drop.
LEADS_ON_VEHICLE = """
select l.id from leads l
  join pipeline_stages s on s.id = l.stage_id
 where l.vehicle_id = $1 and s.category = 'open'
"""

#: Leads with no car yet, whose profile names this make and model. The match is
#: a substring of what the customer themselves wrote — "Hilux GR Sport, white"
#: contains "Hilux" — which is as much cleverness as an arrival alert deserves.
LEADS_WANTING = """
select l.id from leads l
  join pipeline_stages s on s.id = l.stage_id
  join contacts ct on ct.id = l.contact_id
 where l.tenant_id = $1 and l.vehicle_id is null and s.category = 'open'
   and ct.profile->'interest'->>'value' ilike '%' || $2 || '%'
"""

#: The tail a follow-up is judged against.
FOLLOWUP_TAIL = """
select direction, coalesce(nullif(body, ''), transcript->>'text', '') as text
  from (
    select * from messages
     where conversation_id = $1 and kind = 'message'
     order by created_at desc limit 10
  ) recent
 order by created_at
"""

#: A template that fits the reason, when the window has closed.
TEMPLATE_BY_NAME = """
select id, name, language, category, body, variables
  from message_templates
 where channel_id = $1 and status = 'approved' and name = any($2::text[])
 order by array_position($2::text[], name), split_part(language, '_', 1) = $3 desc
 limit 1
"""

#: The open lead a conversation belongs to, when the check was scheduled by a
#: reply rather than aimed at a particular lead.
LEAD_FOR_CONVERSATION = """
select l.id from leads l
  join pipeline_stages s on s.id = l.stage_id
 where l.conversation_id = $1 and s.category = 'open'
 order by l.created_at desc limit 1
"""
