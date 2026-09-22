-- =============================================================================
-- 0010_sales_copilot — Sales S4: what the AI proposed, and the documents it
-- reads. See docs/sales/02-data-model.md § 2 and docs/sales/04-ai-copilot.md § 7.
-- =============================================================================

-- =============================================================================
-- WHAT THE AI PROPOSED
-- Kept apart from what was sent. A salesperson edits a draft before sending it
-- more often than not, and if the edit landed on this row the acceptance metric
-- would measure nothing: every draft would look perfect by the time anyone
-- counted. `text` is the proposal, forever; `final_message_id` is what went.
-- =============================================================================
create table ai_suggestions (
  id               uuid primary key default gen_random_uuid(),
  tenant_id        uuid not null references tenants(id) on delete cascade,
  conversation_id  uuid not null references conversations(id) on delete cascade,
  -- The customer message this answers. Null once that message is purged by the
  -- retention job, which must not take the acceptance history with it.
  for_message_id   uuid references messages(id) on delete set null,
  run_id           uuid references agent_runs(id) on delete set null,
  status           text not null default 'generating'
                     check (status in ('generating', 'ready', 'blocked', 'superseded')),
  text             text,
  -- {template_id, name, variables} — proposed instead of text when the 24-hour
  -- window is closed and only an approved template may be sent.
  template         jsonb,
  language         text check (language in ('ar', 'en', 'fr')),
  intent           text,
  confidence       text check (confidence in ('high', 'medium', 'low')),
  -- [{kind: 'vehicle'|'document', ...}] — what the draft was built from, shown
  -- as chips under it. A fact-bearing draft with an empty array cannot be high
  -- confidence (docs/sales/04-ai-copilot.md § 3).
  sources          jsonb not null default '[]'::jsonb,
  actions          jsonb not null default '[]'::jsonb,
  needs_human      text,
  blocked_reason   text,
  outcome          text check (outcome in ('sent', 'edited', 'discarded')),
  outcome_at       timestamptz,
  outcome_by       uuid references auth.users(id) on delete set null,
  final_message_id uuid references messages(id) on delete set null,
  -- 1 - difflib.SequenceMatcher(draft, final).ratio(). <= 0.2 counts as accepted.
  edit_ratio       numeric(4,3),
  discard_reason   text,
  created_at       timestamptz not null default now()
);

-- At most one live draft per conversation, enforced where it cannot be
-- forgotten. The handler supersedes the old one in the same transaction that
-- creates the new one, and this index is what makes that ordering mandatory
-- rather than merely intended.
create unique index ai_suggestions_live_uq on ai_suggestions (conversation_id)
  where status in ('generating', 'ready');
create index on ai_suggestions (tenant_id, conversation_id, created_at desc);
-- Serves the acceptance view S6 builds, and the eval report's "by intent" table.
create index on ai_suggestions (tenant_id, intent, outcome) where outcome is not null;

-- A suggestion is visible exactly when its conversation is: the same `exists`
-- the messages policy uses, and for the same reason — one rule about who sees a
-- conversation, applied everywhere, instead of a second rule to keep in step.
alter table ai_suggestions enable row level security;
alter table ai_suggestions force row level security;
create policy tenant_visibility on ai_suggestions
  using (
    app.has_tenant_access(tenant_id)
    and exists (select 1 from public.conversations c where c.id = ai_suggestions.conversation_id)
  )
  with check (app.has_tenant_access(tenant_id));
revoke all on ai_suggestions from anon, authenticated;
grant select, insert, update, delete on ai_suggestions to dealerai_app;

-- =============================================================================
-- A DRAFT HAS TO REACH THE PERSON HOLDING THE CONVERSATION
-- Without this, `ai_suggestions` notifies with no owner_id, no assigned_to and
-- no team_id — and realtime.py's filter reads that as "nobody with a scope may
-- see it". The draft would then stream to owners, admins and viewers and never
-- to the salesperson it was written for, which is precisely backwards.
-- A suggestion carries its conversation's visibility, exactly as a message does.
-- =============================================================================
create or replace function app.notify_rt()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $fn$
declare
  row_json jsonb := to_jsonb(new);
  conversation public.conversations%rowtype;
  payload jsonb;
begin
  -- Bulk work (the history import) sets this and emits one summary itself.
  if coalesce(current_setting('app.suppress_rt', true), '') = 'on' then
    return null;
  end if;

  if tg_table_name in ('messages', 'ai_suggestions') then
    select * into conversation from public.conversations c where c.id = new.conversation_id;
  elsif tg_table_name = 'conversations' then
    conversation := new;
  end if;

  payload := jsonb_build_object(
    'tenant_id', row_json->>'tenant_id',
    'type', tg_argv[0],
    'id', row_json->>'id',
    'conversation_id', coalesce(row_json->>'conversation_id', conversation.id::text),
    'owner_id', coalesce(row_json->>'owner_id', conversation.owner_id::text),
    'assigned_to', coalesce(row_json->>'assigned_to', row_json->>'assignee_id',
                            conversation.assigned_to::text),
    'team_id', coalesce(row_json->>'team_id', conversation.team_id::text),
    'user_id', row_json->>'user_id'
  );
  perform pg_notify('rt', payload::text);
  return null;
end $fn$;

revoke all on function app.notify_rt() from public;

create trigger ai_suggestions_rt after insert or update on ai_suggestions
  for each row execute function app.notify_rt('suggestion.ready');

-- =============================================================================
-- THREE MORE THINGS WORTH INTERRUPTING SOMEBODY FOR
-- The kinds are a check constraint rather than a lookup table on purpose: a new
-- kind is then a migration a reviewer reads, which is how `contact_assigned`
-- was caught missing in S3 rather than in production.
-- =============================================================================
alter table notifications drop constraint notifications_kind_check;
alter table notifications add constraint notifications_kind_check check (kind in
  ('message_received', 'assigned', 'waiting_due_soon', 'waiting_missed',
   'unassigned_waiting', 'template_rejected', 'channel_disconnected',
   'channel_quality', 'contact_assigned', 'lead_hot', 'followup_ready',
   'ai_budget_exhausted'));

-- =============================================================================
-- THE DEALERSHIP'S OWN DOCUMENTS
-- doc_chunks has existed since 0001 and has never held a row, so the dimension
-- is free to change today and expensive to change once Pollux has uploaded its
-- export policy. gemini-embedding-001 is a Matryoshka model: 3072 native, and
-- 1536 is a supported truncation that halves the index for no measurable recall
-- loss on documents this size (the check is in tests/evals). Truncated vectors
-- are NOT unit length — ai/embeddings.py re-normalises, without which cosine
-- distance quietly stops meaning what the HNSW index assumes it means.
-- =============================================================================
-- The index first: pgvector cannot rebuild an HNSW index across a dimension
-- change, and leaving it in place makes the ALTER fail rather than the build.
drop index if exists doc_chunks_embedding_idx;
delete from doc_chunks;  -- empty in every environment; makes the alter honest
alter table doc_chunks alter column embedding type vector(1536);
create index doc_chunks_embedding_idx on doc_chunks
  using hnsw (embedding vector_cosine_ops);

-- Hybrid retrieval: the vector index answers "close in meaning", this one
-- answers "contains the word". `simple` rather than a language configuration
-- for the same reason as messages — one tenant's documents mix Arabic, English
-- and French, and stemming for one mangles the other two.
create index doc_chunks_fts_idx on doc_chunks
  using gin (to_tsvector('simple', content));
create index doc_chunks_document_idx on doc_chunks (tenant_id, document_id, chunk_index);

-- What a salesperson uploaded, and what became of it: `failed` needs a reason
-- somebody can read in Settings, not a worker log line.
alter table documents add column if not exists error text;
