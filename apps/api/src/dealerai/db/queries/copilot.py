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
