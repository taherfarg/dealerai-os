# Sales S1 — WhatsApp Channel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** a customer's WhatsApp message — text or voice note — becomes a stored message on the
right customer and conversation, and a salesperson's reply goes out through WhatsApp under the
24-hour window rule, with delivery statuses, templates and a local simulator.

**Architecture:** `POST /webhooks/whatsapp` verifies Meta's signature, stores the delivery, routes
it to a tenant through a SECURITY DEFINER function and enqueues one event per item. Worker handlers
resolve the customer (BSUID first), write messages idempotently, download media to storage and
transcribe voice notes through the model gateway. Sends are a `queued → sending → sent` state machine
with a watchdog, so a crash can never double-send. Everything runs offline against a mock connector
and a simulator that posts real signed payloads.

**Tech stack:** Postgres 17 · asyncpg · FastAPI · Pydantic v2 · httpx · google-genai (Gemini 2.5
Flash for audio) · pytest · ffmpeg (once, to make the sample voice note).

**Before you start:**

- Docker Desktop running; in this worktree prefix database commands with
  `COMPOSE_PROJECT_NAME=dealeraios` (otherwise compose fights the main checkout for port 54332).
- Work on branch `sales/phase-1`. Run checks with `set -o pipefail` — piping pytest or mypy into
  `tail` once hid a failure.
- Read [../03-whatsapp.md](../03-whatsapp.md) §4–§8 and [../05-workflows.md](../05-workflows.md) §2–§3:
  they are the specification this plan implements.
- Meta facts re-checked on 2026-09-17: the BSUID arrives as `contacts[].user_id`,
  `messages[].from_user_id` and `statuses[].recipient_user_id`; `wa_id` / `from` can be absent;
  sends take `to` (phone) or `recipient` (BSUID); `user_id_update` carries
  `user_id.previous` / `user_id.current`; Graph API is v25.0; Gemini 2.5 Flash transcribes
  `audio/ogg` (Opus) directly — audio input $1.00 per 1M tokens, cached $0.10, output $2.50.

---

## Execution status — 2026-09-18

Tasks 1–5 below were implemented as written. The continuation was completed test-first in the
following commits:

| Commit | Delivered |
|---|---|
| `146135a` | Signed webhook verification, persistence, routing and event fan-out |
| `ded6039` | BSUID-first identity resolution with advisory-lock concurrency safety |
| `8e6b276` | Idempotent inbound message ingest, service window and follow-up events |
| `4541523` | Monotonic delivery/read/failure statuses and bounded race retries |
| `f610bbd` | Immediate media storage and budgeted voice-note transcription |
| `4c145b3` | Idempotent outbound queue, safe send claim and delivery-unknown watchdog |
| `f3d677d` | Channel/template APIs, template sync and rejection handling |
| `4251164` | WhatsApp Business phone-app echo ingest and BSUID changes |
| `f9b55df` | Account revocation and phone-number quality handling |
| `1b19911` | Pollux local WhatsApp seed, mock connector and signed webhook simulator |

The local exit path is covered: a signed simulated customer message routes to the correct tenant,
becomes an inbox message, media is stored before downstream work, voice transcription is attached,
and an idempotent human reply is sent once through the mock connector. Live Meta test-number smoke
and Tech Provider approval remain operational gates; coexistence onboarding and history import are
the later S10 workflow slice.

## Review — 2026-09-19

The implementation above was reviewed against this plan and the specs, and the exit path was
run end to end for the first time. The suite was green throughout, so each of these was
invisible to it.

| Found | Why it mattered | Fixed in |
|---|---|---|
| `npm run wa:simulate inbound` never produced a message: the simulator sent the BSUID as `wa_id`, and the resolver raised on anything that is not a phone number | The documented demo path, and the slice's own exit criterion. Only the payload shape was tested, never its journey | `34bae10` |
| Every connector failure marked the message `failed`, including timeouts and 5xx | A clean "failed" invites a retry that sends the customer the same message twice — the one mistake the watchdog exists to prevent. A rate limit also failed a reply Meta never received | `1649194` |
| Eleven event types were emitted with nothing handling them, four on every inbound message | An unhandled type retries five times and dead-letters, so working software fills the queue with red | `edde940` |
| The three authenticated endpoints had no permission or visibility test; another tenant's channel answered `[]` rather than 404 | The definition of done requires both of every endpoint | `a6d00d0` |
| Route errors were the connector's own types, not the contract's | The composer branches on `window-closed` to offer templates; `channel-unavailable` is a 409 | `a6d00d0` |
| The mock served 21 placeholder bytes as a voice note | Gemini transcribes whatever it is handed: the demo attached invented speech that looked exactly like a working transcript | `34bae10` |
| Transcripts carried no language, and silence became a plausible car enquiry | The fake in the test supplied a language the real function never returned. Fabricated customer speech is worse than no transcript | `b4d2462` |

Sound as built, and left alone: the migration, the advisory-lock identity resolution, status
monotonicity, media idempotence, the audio-rate cost model and the watchdog itself.

Known and deliberately not changed in S1: `sla_due_at` ignores business hours until
`sales/hours.py` arrives with S2; inbound interactive replies and button taps store as
`unsupported`; template variables are numbered rather than labelled; an inbound message
reopens a conversation marked spam.

**Verified end to end on 2026-09-19** (signed simulated webhook → worker → database):
a voice note became an `audio` message on the right customer, its media was stored on disk,
Gemini returned *"Hello, is the white Land Cruiser still available? What is your best price?"*,
a salesperson's reply was queued, claimed once and sent through the mock, and the queue
finished with no failures.

---

## File structure

| File | Responsibility |
|---|---|
| `supabase/migrations/0007_sales_whatsapp.sql` | **Create.** Channel routing columns, WhatsApp message columns, `message_templates`, `app.route_whatsapp` |
| `apps/api/src/dealerai/config.py` | **Modify.** `WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_GRAPH_VERSION`, `STORAGE_DIR` |
| `apps/api/src/dealerai/media/storage.py` | **Modify.** Local-disk backend for development; `extension_for` |
| `apps/api/src/dealerai/sales/messaging.py` | **Create.** Pure rules: window, opt-out, template consent, template rendering |
| `apps/api/src/dealerai/sales/identity.py` | **Create.** WhatsApp identity → customer, serialised by an advisory lock |
| `apps/api/src/dealerai/connectors/base.py` | **Modify.** `MessagingConnector`, `TemplateInfo`, `RequestRejected`, `MessageRequest.template_language` |
| `apps/api/src/dealerai/connectors/mock.py` | **Modify.** Media and templates on the mock; `whatsapp_simulator()` |
| `apps/api/src/dealerai/connectors/whatsapp.py` | **Create.** Cloud API client, webhook message parsing, template helpers, `for_channel` |
| `apps/api/src/dealerai/connectors/samples/voice-note.ogg` | **Create.** The simulator's voice note (real speech, Opus) |
| `apps/api/src/dealerai/routes/webhooks.py` | **Create.** Meta's challenge; verify → persist → route → enqueue |
| `apps/api/src/dealerai/routes/channels.py` | **Create.** `GET /v1/channels`, templates list, template sync |
| `apps/api/src/dealerai/routes/inbox.py` | **Create.** `POST /v1/conversations/{id}/messages` |
| `apps/api/src/dealerai/events/bus.py`, `events/worker.py` | **Modify.** `Event.max_attempts`, so a handler knows its last try |
| `apps/api/src/dealerai/events/handlers/whatsapp.py` | **Create.** Inbound message, BSUID change, status, template status, template sync |
| `apps/api/src/dealerai/events/handlers/inbox.py` | **Create.** Media download, transcription, send, send watchdog |
| `apps/api/src/dealerai/media/transcribe.py`, `ai/prompts/transcribe.md` | **Create.** Voice note → transcript through the gateway |
| `apps/api/src/dealerai/ai/models.py` | **Modify.** `TaskKind.TRANSCRIBE`, priced at the audio rate |
| `apps/api/src/dealerai/db/session.py` | **Modify.** Docstring: the webhook is a legitimate `system_session` use |
| `apps/api/src/dealerai/scripts/seed_sales.py` | **Modify.** The simulator's WhatsApp channel |
| `apps/api/src/dealerai/scripts/wa_simulate.py` | **Create.** `npm run wa:simulate` |
| `apps/api/src/dealerai/scripts/wa_channel.py` | **Create.** Connect Meta's test number by hand (local, until S5) |
| `apps/api/tests/connectors/fixtures/whatsapp/*.json` | **Create.** One anonymised payload per webhook item type |
| `apps/api/tests/connectors/test_messaging_contract.py` | **Create.** The suite every messaging connector passes |
| `apps/api/tests/test_whatsapp_*.py`, `test_sales_messaging.py`, `test_identity.py`, `test_storage_local.py`, `test_channels_routes.py`, `test_send_message.py`, `test_wa_scripts.py` | **Create.** One file per task |
| `package.json`, `.env.example`, `.gitignore` | **Modify.** `wa:simulate`, `wa:channel`; new settings; `.storage/` |

---

## Task 1: The schema WhatsApp needs

**Files:**
- Create: `supabase/migrations/0007_sales_whatsapp.sql`
- Create: `apps/api/tests/test_whatsapp_schema.py`
- Modify: `apps/api/tests/conftest.py` (the message insert in `_seed_tenant`)
- Modify: `apps/api/tests/test_visibility.py` (the message insert in `test_messages_follow_their_conversation`)

The existing structural tests already cover the new table: `test_every_tenant_table_has_forced_rls`
fails if `message_templates` lacks forced RLS, and `test_browser_roles_cannot_read_any_table` fails
if a browser role can reach it. Do not duplicate them.

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/test_whatsapp_schema.py
"""What 0007_sales_whatsapp.sql must be true about, before any handler relies on it."""

from __future__ import annotations

import uuid

import asyncpg
import pytest

from conftest import TENANT_A, TENANT_B
from dealerai.db.session import system_session


async def _channel(
    su: asyncpg.Connection, tenant_id: uuid.UUID, phone_number_id: str, waba_id: str = "waba-1"
) -> uuid.UUID:
    return await su.fetchval(
        """insert into channels (tenant_id, platform, external_id, account_id, mode)
           values ($1, 'whatsapp', $2, $3, 'cloud_api') returning id""",
        tenant_id,
        phone_number_id,
        waba_id,
    )


async def _conversation(su: asyncpg.Connection, tenant_id: uuid.UUID) -> uuid.UUID:
    return await su.fetchval("select id from conversations where tenant_id = $1", tenant_id)


async def test_a_phone_number_belongs_to_one_tenant(su: asyncpg.Connection, seeded: None) -> None:
    """Webhooks route by phone_number_id before any tenant is known."""
    await _channel(su, TENANT_A, "15550001")
    with pytest.raises(asyncpg.UniqueViolationError):
        await _channel(su, TENANT_B, "15550001")


async def test_routing_works_before_any_tenant_is_known(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    channel_id = await _channel(su, TENANT_A, "15550001", "waba-a")
    async with system_session() as conn:
        by_number = await conn.fetch(
            "select tenant_id, channel_id from app.route_whatsapp($1, $2)", "15550001", "other"
        )
        by_account = await conn.fetch(
            "select tenant_id, channel_id from app.route_whatsapp($1, $2)", None, "waba-a"
        )
        unknown = await conn.fetch(
            "select tenant_id, channel_id from app.route_whatsapp($1, $2)", "nope", "nope"
        )
    assert [(r["tenant_id"], r["channel_id"]) for r in by_number] == [(TENANT_A, channel_id)]
    assert [(r["tenant_id"], r["channel_id"]) for r in by_account] == [(TENANT_A, channel_id)]
    assert unknown == []


async def test_only_the_api_role_may_route(su: asyncpg.Connection) -> None:
    fn = "app.route_whatsapp(text, text)"
    assert await su.fetchval("select has_function_privilege('dealerai_app', $1, 'execute')", fn)
    for role in ("anon", "authenticated"):
        assert not await su.fetchval(
            "select has_function_privilege($1, $2, 'execute')", role, fn
        ), f"{role} can map phone numbers to tenants"


async def test_a_whatsapp_message_id_is_unique_per_tenant(
    su: asyncpg.Connection, seeded: None
) -> None:
    """History import and a live webhook can deliver the same id through two paths."""
    conversation = await _conversation(su, TENANT_A)
    contact = await su.fetchval("select contact_id from conversations where id = $1", conversation)
    other = await su.fetchval(
        """insert into conversations (tenant_id, contact_id, surface)
           values ($1, $2, 'whatsapp') returning id""",
        TENANT_A,
        contact,
    )
    insert = """insert into messages (tenant_id, conversation_id, direction, sender, origin,
                                      external_id)
                values ($1, $2, 'in', 'customer', 'customer', 'wamid.same')"""
    await su.execute(insert, TENANT_A, conversation)
    with pytest.raises(asyncpg.UniqueViolationError):
        await su.execute(insert, TENANT_A, other)
    await su.execute(insert, TENANT_B, await _conversation(su, TENANT_B))


async def test_an_idempotency_key_creates_one_message(su: asyncpg.Connection, seeded: None) -> None:
    conversation = await _conversation(su, TENANT_A)
    insert = """insert into messages (tenant_id, conversation_id, direction, sender, origin,
                                      status, idempotency_key)
                values ($1, $2, 'out', 'human', 'inbox', 'queued', 'key-1')"""
    await su.execute(insert, TENANT_A, conversation)
    with pytest.raises(asyncpg.UniqueViolationError):
        await su.execute(insert, TENANT_A, conversation)


async def test_sending_is_a_status(su: asyncpg.Connection, seeded: None) -> None:
    await su.execute(
        """insert into messages (tenant_id, conversation_id, direction, sender, origin, status)
           values ($1, $2, 'out', 'human', 'inbox', 'sending')""",
        TENANT_A,
        await _conversation(su, TENANT_A),
    )


async def test_every_message_says_where_it_came_from(su: asyncpg.Connection, seeded: None) -> None:
    with pytest.raises(asyncpg.NotNullViolationError):
        await su.execute(
            """insert into messages (tenant_id, conversation_id, direction, sender)
               values ($1, $2, 'in', 'customer')""",
            TENANT_A,
            await _conversation(su, TENANT_A),
        )


async def test_errors_are_structured(su: asyncpg.Connection, seeded: None) -> None:
    error = {"code": "131047", "message": "Re-engagement message"}
    message_id = await su.fetchval(
        """insert into messages (tenant_id, conversation_id, direction, sender, origin, status,
                                 error)
           values ($1, $2, 'out', 'human', 'inbox', 'failed', $3::jsonb) returning id""",
        TENANT_A,
        await _conversation(su, TENANT_A),
        '{"code": "131047", "message": "Re-engagement message"}',
    )
    stored = await su.fetchval("select error::text from messages where id = $1", message_id)
    assert stored is not None and "131047" in stored and error["message"] in stored
```

`su` is a raw `asyncpg.connect`, which has no jsonb codec — that is why the last test passes a
JSON string and reads `::text`.

- [ ] **Step 2: Run it to verify it fails**

Run: `cd apps/api && uv run pytest tests/test_whatsapp_schema.py -v`
Expected: FAIL — `column "account_id" of relation "channels" does not exist`, and
`function app.route_whatsapp(text, text) does not exist`.

- [ ] **Step 3: Write the migration**

```sql
-- supabase/migrations/0007_sales_whatsapp.sql
-- =============================================================================
-- 0007_sales_whatsapp — Sales S1: the WhatsApp channel.
-- See docs/sales/03-whatsapp.md and docs/sales/02-data-model.md § 3.
-- =============================================================================

-- =============================================================================
-- CHANNELS
-- A phone number belongs to one tenant, ever. Webhooks route by it before any
-- tenant context exists, so uniqueness per tenant is not enough.
-- =============================================================================
alter table channels
  add column mode text check (mode in ('cloud_api', 'coexistence')),
  add column account_id text,
  add column sync_state jsonb not null default '{}'::jsonb,
  add column quality_rating text check (quality_rating in ('green', 'yellow', 'red'));

alter table channels drop constraint channels_tenant_id_platform_external_id_key;
alter table channels add constraint channels_platform_external_id_key
  unique (platform, external_id);
create index on channels (platform, account_id);

-- =============================================================================
-- MESSAGES
-- One row shape for every WhatsApp type. `origin` is required: a thread that
-- cannot tell the customer from the phone app from the inbox is not an audit.
-- =============================================================================
alter table messages drop constraint messages_status_check;
alter table messages add constraint messages_status_check check (status in
  ('draft', 'pending_approval', 'queued', 'sending', 'sent', 'delivered', 'read', 'failed'));

alter table messages
  add column kind text not null default 'message'
    check (kind in ('message', 'note', 'event')),
  add column type text not null default 'text'
    check (type in ('text', 'image', 'audio', 'video', 'document', 'location', 'sticker',
                    'template', 'interactive_reply', 'vehicle_card', 'unsupported')),
  add column origin text
    check (origin in ('customer', 'inbox', 'phone_app', 'history', 'system', 'ai')),
  add column author_user_id uuid references auth.users(id) on delete set null,
  add column transcript jsonb,
  add column location jsonb,
  add column template jsonb,
  add column reply_to_id uuid references messages(id) on delete set null,
  add column reactions jsonb not null default '[]'::jsonb,
  add column referral jsonb,
  add column pricing jsonb,
  add column event jsonb,
  add column delivered_at timestamptz,
  add column read_at timestamptz,
  -- set when a send moves queued → sending; the watchdog reads it (03 § 7)
  add column locked_at timestamptz,
  add column idempotency_key text;

update messages set origin = case when direction = 'in' then 'customer' else 'inbox' end;
alter table messages alter column origin set not null;

-- {code, message}: Meta's error code and the readable cause the inbox shows.
alter table messages alter column error type jsonb
  using case when error is null then null
             else jsonb_build_object('code', 'unknown', 'message', error) end;

-- WhatsApp message ids are globally unique, and history import and a live
-- webhook can deliver the same id into different code paths.
drop index messages_external_uq;
create unique index messages_external_uq on messages (tenant_id, external_id)
  where external_id is not null;
create unique index messages_idempotency_uq on messages (tenant_id, idempotency_key)
  where idempotency_key is not null;

-- =============================================================================
-- MESSAGE TEMPLATES — synced from the WABA; `components` kept verbatim for sending
-- =============================================================================
create table message_templates (
  id              uuid primary key default gen_random_uuid(),
  tenant_id       uuid not null references tenants(id) on delete cascade,
  channel_id      uuid not null references channels(id) on delete cascade,
  external_id     text not null,
  name            text not null,
  language        text not null,
  category        text not null check (category in ('marketing', 'utility', 'authentication')),
  status          text not null
                    check (status in ('approved', 'pending', 'rejected', 'paused', 'disabled')),
  components      jsonb not null default '[]'::jsonb,
  body            text not null default '',
  variables       text[] not null default '{}',
  rejected_reason text,
  synced_at       timestamptz not null default now(),
  unique (channel_id, name, language)
);
create index on message_templates (tenant_id, channel_id, status);

alter table message_templates enable row level security;
alter table message_templates force row level security;
create policy tenant_isolation on message_templates
  using (app.has_tenant_access(tenant_id))
  with check (app.has_tenant_access(tenant_id));

-- On Supabase a new table inherits default privileges for the browser roles
-- (see 0006): repeat the revoke for every table a Sales migration adds.
revoke all on message_templates from anon, authenticated;

-- =============================================================================
-- WEBHOOK ROUTING
-- The query that finds the tenant, so it runs before one is known — the same
-- treatment as app.member_role in 0004. Account-level webhooks (template status)
-- carry no phone number and route by WABA id.
-- =============================================================================
create or replace function app.route_whatsapp(p_phone_number_id text, p_account_id text)
returns table (tenant_id uuid, channel_id uuid)
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  select c.tenant_id, c.id
  from public.channels c
  where c.platform = 'whatsapp'
    and case when p_phone_number_id is not null then c.external_id = p_phone_number_id
             else c.account_id = p_account_id end
$$;

revoke all on function app.route_whatsapp(text, text) from public;
grant execute on function app.route_whatsapp(text, text) to dealerai_app;
```

- [ ] **Step 4: Give the two existing message inserts an origin**

In `apps/api/tests/conftest.py`, `_seed_tenant`:

```python
    await conn.execute(
        """insert into messages (tenant_id, conversation_id, direction, sender, origin, body)
           values ($1, $2, 'in', 'customer', 'customer', $3)""",
        tenant_id,
        conversation_id,
        f"secret of {slug}",
    )
```

In `apps/api/tests/test_visibility.py`, `test_messages_follow_their_conversation`:

```python
        await su.execute(
            """insert into messages (tenant_id, conversation_id, direction, sender, origin, body)
               values ($1, $2, 'in', 'customer', 'customer', $3)""",
            TENANT_A,
            conversation_id,
            f"secret of {key}",
        )
```

- [ ] **Step 5: Run the tests**

The `_migrated` fixture applies `0007` on the next run. If you edit the migration after it has been
applied, the runner refuses the changed checksum: `COMPOSE_PROJECT_NAME=dealeraios npm run db:reset`.

Run: `cd apps/api && uv run pytest tests/test_whatsapp_schema.py tests/test_tenant_isolation.py tests/test_visibility.py -v`
Expected: PASS, including `test_every_tenant_table_has_forced_rls` and
`test_browser_roles_cannot_read_any_table` with `message_templates` present.

Then the whole suite: `set -o pipefail; npm run test 2>&1 | tail -3`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add supabase/migrations/0007_sales_whatsapp.sql apps/api/tests/test_whatsapp_schema.py apps/api/tests/conftest.py apps/api/tests/test_visibility.py
git commit -m "feat(sales): schema for the WhatsApp channel"
```

---

## Task 2: Settings, and storage that works offline

**Files:**
- Modify: `apps/api/src/dealerai/config.py`
- Modify: `.env.example`, `.gitignore`
- Modify: `apps/api/src/dealerai/media/storage.py`
- Create: `apps/api/tests/test_storage_local.py`

The local stack is a bare Postgres container, with no Storage API behind it. Without a disk backend a
simulated voice note cannot be stored, and the S1 exit demo would depend on a remote bucket nobody
has checked. `STORAGE_DIR` is refused outside `ENV=local`: a container's disk disappears on redeploy,
and a customer's voice note must not.

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/test_storage_local.py
"""Local development keeps stored objects on disk, and nowhere else may."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from dealerai.config import get_settings
from dealerai.media import storage

TENANT = UUID("aaaaaaaa-0000-4000-8000-000000000001")


@pytest.fixture
def local_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(get_settings(), "storage_dir", str(tmp_path))
    monkeypatch.setattr(get_settings(), "env", "local")
    return tmp_path


async def test_round_trip_on_disk(local_dir: Path) -> None:
    path = storage.object_path(TENANT, "messages", "ogg")
    assert await storage.upload(path, b"OggS voice", content_type="audio/ogg") == path
    assert (local_dir / path).read_bytes() == b"OggS voice"
    assert await storage.download(path) == b"OggS voice"


async def test_objects_are_never_overwritten(local_dir: Path) -> None:
    path = storage.object_path(TENANT, "messages", "ogg")
    await storage.upload(path, b"first", content_type="audio/ogg")
    with pytest.raises(storage.StorageUnavailable):
        await storage.upload(path, b"second", content_type="audio/ogg")


async def test_a_missing_object_is_not_found(local_dir: Path) -> None:
    with pytest.raises(storage.ObjectNotFound):
        await storage.download(f"{TENANT}/messages/2026/09/missing.ogg")


async def test_a_path_cannot_escape_the_directory(local_dir: Path) -> None:
    with pytest.raises(storage.ObjectNotFound):
        await storage.download("../../outside.txt")


async def test_disk_storage_is_refused_outside_local(
    local_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "env", "staging")
    with pytest.raises(storage.StorageUnavailable):
        await storage.upload("x/y.ogg", b"data", content_type="audio/ogg")


@pytest.mark.parametrize(
    ("mime", "filename", "expected"),
    [
        ("audio/ogg; codecs=opus", None, "ogg"),
        ("image/jpeg", None, "jpg"),
        ("application/pdf", "Invoice 2291.PDF", "pdf"),
        ("application/pdf", "no-extension", "pdf"),
        ("application/octet-stream", None, "bin"),
    ],
)
def test_extension_for(mime: str, filename: str | None, expected: str) -> None:
    assert storage.extension_for(mime, filename) == expected
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd apps/api && uv run pytest tests/test_storage_local.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'storage_dir'` (pydantic
refuses to set an undeclared field) and `module 'dealerai.media.storage' has no attribute 'extension_for'`.

- [ ] **Step 3: Declare the settings**

In `apps/api/src/dealerai/config.py`, after `web_origins`:

```python
    #: Meta app secret. Every webhook body is verified against it
    #: (X-Hub-Signature-256); unset, every webhook is refused.
    whatsapp_app_secret: str | None = None

    #: The string Meta echoes back when the webhook subscription is verified.
    whatsapp_verify_token: str | None = None

    #: Graph API version the WhatsApp connector calls. Meta keeps a version about two years.
    whatsapp_graph_version: str = "v25.0"

    #: Local development only: stored objects live in this directory instead of
    #: Supabase Storage. Relative paths resolve against the repo root.
    storage_dir: str | None = None
```

In `.env.example`, after `WEB_ORIGINS`:

```bash
# WhatsApp Cloud API (docs/sales/03-whatsapp.md). Locally any strings work: the
# simulator (npm run wa:simulate) signs with the same secret. Real values come from
# the Meta app dashboard, and the secret authenticates every webhook — treat it as one.
WHATSAPP_APP_SECRET=
WHATSAPP_VERIFY_TOKEN=
WHATSAPP_GRAPH_VERSION=v25.0

# Local development only: stored objects go to this folder instead of Supabase
# Storage. The API refuses it outside ENV=local.
STORAGE_DIR=.storage
```

In `.gitignore`, under `# local infra + generated media`:

```
.storage/
```

Then give your own `.env` (gitignored) local values, generated rather than typed:

```bash
printf '\nWHATSAPP_APP_SECRET=%s\nWHATSAPP_VERIFY_TOKEN=%s\nWHATSAPP_GRAPH_VERSION=v25.0\nSTORAGE_DIR=.storage\n' "$(openssl rand -hex 16)" "$(openssl rand -hex 8)" >> .env
```

- [ ] **Step 4: Add the disk backend and `extension_for`**

In `apps/api/src/dealerai/media/storage.py`, extend the imports:

```python
import asyncio
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import httpx

from ..config import get_settings, repo_root
from ..core.errors import AppError
```

Add below `BUCKET = "media"`:

```python
#: What WhatsApp sends, mapped to the extension a stored object gets.
_EXTENSIONS = {
    "audio/ogg": "ogg",
    "audio/mpeg": "mp3",
    "audio/mp4": "m4a",
    "audio/aac": "aac",
    "audio/amr": "amr",
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "video/mp4": "mp4",
    "video/3gpp": "3gp",
    "application/pdf": "pdf",
}


def extension_for(mime: str, filename: str | None = None) -> str:
    """The customer's own extension when it is sane, otherwise the type's."""
    if filename and "." in filename:
        extension = filename.rsplit(".", 1)[1].lower()
        if extension.isalnum() and len(extension) <= 8:
            return extension
    return _EXTENSIONS.get(mime.split(";")[0].strip().lower(), "bin")


def _local_root() -> Path | None:
    """STORAGE_DIR, when set: objects on disk, for a laptop with no Supabase project."""
    settings = get_settings()
    if not settings.storage_dir:
        return None
    if not settings.is_local:
        # A container's disk vanishes on redeploy; a customer's voice note must not.
        raise StorageUnavailable("STORAGE_DIR is for local development only")
    root = Path(settings.storage_dir)
    return root if root.is_absolute() else repo_root() / root


def _local_path(root: Path, storage_path: str) -> Path:
    path = (root / storage_path.lstrip("/")).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ObjectNotFound(storage_path)
    return path


def _read(root: Path, storage_path: str) -> bytes:
    path = _local_path(root, storage_path)
    if not path.is_file():
        raise ObjectNotFound(storage_path)
    return path.read_bytes()


def _write(root: Path, storage_path: str, data: bytes) -> None:
    path = _local_path(root, storage_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        # "x": never overwrite, the same promise as x-upsert: false below.
        with path.open("xb") as handle:
            handle.write(data)
    except FileExistsError as exc:
        raise StorageUnavailable(f"object already exists: {storage_path}") from exc
```

At the top of `download`, before the Supabase code:

```python
    root = _local_root()
    if root is not None:
        return await asyncio.to_thread(_read, root, storage_path)
```

At the top of `upload`, before the Supabase code:

```python
    root = _local_root()
    if root is not None:
        await asyncio.to_thread(_write, root, storage_path, data)
        return storage_path
```

- [ ] **Step 5: Run the tests**

Run: `cd apps/api && uv run pytest tests/test_storage_local.py tests/test_config.py tests/test_content.py -v`
Expected: PASS — `test_env_example_covers_every_setting` confirms the four settings are documented,
and the content tests (which stub storage) are unaffected.

- [ ] **Step 6: Commit**

```bash
git add apps/api/src/dealerai/config.py .env.example .gitignore apps/api/src/dealerai/media/storage.py apps/api/tests/test_storage_local.py
git commit -m "feat(sales): WhatsApp settings and local disk storage"
```

---

## Task 3: The send rules, as pure functions

**Files:**
- Create: `apps/api/src/dealerai/sales/__init__.py`
- Create: `apps/api/src/dealerai/sales/messaging.py`
- Create: `apps/api/tests/test_sales_messaging.py`

The route, the send handler and the ingest handler all apply these rules, so they live in one place
with no database and no clock: callers pass `now`, and the tests sit exactly on the edges.
`sales/` imports nothing from `routes`, `events` or `connectors` ([../01-architecture.md](../01-architecture.md) §1).

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/test_sales_messaging.py
"""The send rules at their edges. No database."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from dealerai.sales.messaging import (
    is_opt_out,
    render_template,
    template_block_reason,
    variable_numbers,
    window_is_open,
)

NOW = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "text",
    ["STOP", "Stop.", "  stop  ", "unsubscribe", "Don't message me",
     "لا تراسلني", "إلغاء الاشتراك", "توقف!", "Arrêtez", "Se désabonner"],
)
def test_opt_out_phrases_in_three_languages(text: str) -> None:
    assert is_opt_out(text)


@pytest.mark.parametrize(
    "text",
    [None, "", "Can you stop by the showroom tomorrow?", "stop, the price is too high",
     "توقف السعر عند كم؟", "Arrêtez-vous à Oran ?"],
)
def test_ordinary_messages_are_not_opt_outs(text: str | None) -> None:
    """Whole messages, not words: a customer saying "stop by" is still a customer."""
    assert not is_opt_out(text)


def test_the_window_is_open_until_its_last_instant() -> None:
    expires = NOW + timedelta(hours=24)
    assert window_is_open(expires, expires - timedelta(seconds=1))
    assert not window_is_open(expires, expires)
    assert not window_is_open(None, NOW)


def test_an_opt_out_blocks_every_template() -> None:
    consent = {"opted_out_at": "2026-09-01T10:00:00Z", "marketing": True}
    assert template_block_reason("utility", consent)
    assert template_block_reason("marketing", consent)


def test_marketing_needs_a_recorded_yes() -> None:
    assert template_block_reason("marketing", {})
    assert template_block_reason("marketing", {"marketing": "yes"}), "only the boolean true counts"
    assert template_block_reason("marketing", {"marketing": True}) is None
    assert template_block_reason("utility", {}) is None


def test_render_template_fills_numbered_variables() -> None:
    body = "Hi {{1}}, the {{2}} is now {{3}}."
    assert (
        render_template(body, ["Karim", "Hilux GR Sport", "AED 165,000"])
        == "Hi Karim, the Hilux GR Sport is now AED 165,000."
    )
    assert render_template("Hi {{1}} {{2}}", ["Karim"]) == "Hi Karim {{2}}"


def test_variable_numbers_are_distinct_and_ordered() -> None:
    assert variable_numbers("{{2}} and {{1}} and {{2}} again") == [1, 2]
    assert variable_numbers("no variables") == []
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd apps/api && uv run pytest tests/test_sales_messaging.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dealerai.sales'`.

- [ ] **Step 3: Write the module**

```python
# apps/api/src/dealerai/sales/__init__.py
"""Sales domain logic. Imports nothing from routes, events or connectors."""
```

```python
# apps/api/src/dealerai/sales/messaging.py
"""What may be sent to a customer, as pure functions. docs/sales/03-whatsapp.md § 6.

No database and no clock: callers pass `now`, so the rules are testable at the
exact edge — one second before the window closes — rather than approximately.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

_PUNCTUATION = re.compile(r"[^\w\s]")
_TATWEEL = "ـ"
_VARIABLE = re.compile(r"\{\{(\d+)\}\}")


def _normalise(text: str) -> str:
    """Case, accents, Arabic diacritics and hamza forms, punctuation and spacing away.

    NFKD splits "أ" into alef plus a combining hamza and "ê" into e plus a
    combining circumflex, so dropping combining marks handles Arabic and French
    with one rule.
    """
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    bare = "".join(c for c in decomposed if not unicodedata.combining(c)).replace(_TATWEEL, "")
    return " ".join(_PUNCTUATION.sub("", bare).split())


#: A message that is exactly one of these is an opt-out. Whole messages, not
#: words: "can you stop by the showroom?" is a customer, not an opt-out.
_OPT_OUT = frozenset(
    _normalise(phrase)
    for phrase in (
        "stop", "unsubscribe", "stop messaging me", "don't message me", "do not message me",
        # Not a bare "إلغاء" (cancel): that is how a customer cancels a test drive.
        "توقف", "إلغاء الاشتراك", "لا تراسلني", "لا ترسل لي", "لا ترسلوا لي",
        "arrête", "arrêtez", "stop svp", "désabonner", "se désabonner",
    )
)


def is_opt_out(text: str | None) -> bool:
    return bool(text) and _normalise(text or "") in _OPT_OUT


def window_is_open(expires_at: datetime | None, now: datetime) -> bool:
    """Free-form messages need the customer's last message to be under 24 hours old."""
    return expires_at is not None and now < expires_at


def template_block_reason(category: str, consent: Mapping[str, Any]) -> str | None:
    """Why this template may not go to this customer, or None when it may.

    A template is how a business starts a conversation, so the customer's choices
    apply: an opt-out stops every template, and marketing needs a recorded yes.
    Free-form replies inside the window are answers, not outreach, and are not
    checked here.
    """
    if consent.get("opted_out_at"):
        return "The customer asked not to be messaged."
    if category == "marketing" and consent.get("marketing") is not True:
        return "Marketing templates need the customer's recorded marketing consent."
    return None


def variable_numbers(body: str) -> list[int]:
    """The distinct {{n}} placeholders in a template body, in order."""
    return sorted({int(n) for n in _VARIABLE.findall(body)})


def render_template(body: str, variables: Sequence[str]) -> str:
    """Fill {{1}}, {{2}} … the way WhatsApp will, for the thread and for search."""

    def fill(match: re.Match[str]) -> str:
        index = int(match.group(1)) - 1
        return variables[index] if 0 <= index < len(variables) else match.group(0)

    return _VARIABLE.sub(fill, body)
```

- [ ] **Step 4: Run the tests**

Run: `cd apps/api && uv run pytest tests/test_sales_messaging.py -v && uv run mypy src`
Expected: PASS, and mypy clean.

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/dealerai/sales apps/api/tests/test_sales_messaging.py
git commit -m "feat(sales): send rules for the window, opt-outs and templates"
```

---

## Task 4: A contract for messaging connectors

**Files:**
- Modify: `apps/api/src/dealerai/connectors/base.py`
- Modify: `apps/api/src/dealerai/connectors/mock.py`
- Create: `apps/api/tests/connectors/test_messaging_contract.py`

`SocialConnector` is a publishing contract: WhatsApp cannot publish, fetch comments or report
insights, and `test_contract.py` requires `reply_comment` to return an id. Rather than a WhatsApp
connector full of `NotSupported` stubs, messaging gets its own small protocol with only what S1 uses:
send, download media, list templates. `mark_read` and `upload_media` arrive with the composer (S2);
the coexistence sync calls with S5.

- [ ] **Step 1: Write the failing contract suite**

```python
# apps/api/tests/connectors/test_messaging_contract.py
"""The suite every messaging connector passes, unmodified.

Idempotency is deliberately absent. WhatsApp's send API takes no key, so no
client can promise it; the guarantee is the send handler's state machine
(tests/test_send_message.py).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import pytest

from dealerai.connectors.base import (
    MessageRequest,
    MessagingConnector,
    NotSupported,
    OutsideMessagingWindow,
    RateLimited,
    RequestRejected,
    TemplateInfo,
    TokenExpired,
)
from dealerai.connectors.mock import MockConnector, whatsapp_like


class Controls(Protocol):
    """How a test sets the platform's state, whatever sits behind the connector."""

    def close_window(self) -> None: ...
    def expire_token(self) -> None: ...
    def rate_limit(self, retry_after_seconds: int) -> None: ...
    def add_media(self, media_id: str, data: bytes, mime: str) -> None: ...
    def add_template(self, template: TemplateInfo) -> None: ...


@dataclass
class MockControls:
    mock: MockConnector

    def close_window(self) -> None:
        self.mock.window_open = False

    def expire_token(self) -> None:
        self.mock.fail_next = TokenExpired("reconnect required")

    def rate_limit(self, retry_after_seconds: int) -> None:
        self.mock.fail_next = RateLimited("slow down", retry_after_seconds=retry_after_seconds)

    def add_media(self, media_id: str, data: bytes, mime: str) -> None:
        self.mock.media[media_id] = (data, mime)

    def add_template(self, template: TemplateInfo) -> None:
        self.mock.templates.append(template)


def _mock() -> tuple[MessagingConnector, Controls]:
    mock = whatsapp_like()
    return mock, MockControls(mock)


#: Task 5 appends the Cloud API connector, wired to a fake Graph API.
FACTORIES: list[tuple[str, Callable[[], tuple[MessagingConnector, Controls]]]] = [
    ("mock_whatsapp", _mock),
]

Pair = tuple[MessagingConnector, Controls]

TEMPLATE = TemplateInfo(
    external_id="1234567890",
    name="vehicle_available",
    language="en",
    category="utility",
    status="approved",
    components=[{"type": "BODY", "text": "Hi {{1}}, the {{2}} is available."}],
)


@pytest.fixture(params=[f for _, f in FACTORIES], ids=[n for n, _ in FACTORIES])
def pair(request: pytest.FixtureRequest) -> Pair:
    return request.param()  # type: ignore[no-any-return]


def a_text(recipient: str = "+971500000101", body: str | None = "Hello") -> MessageRequest:
    return MessageRequest(recipient_external_id=recipient, idempotency_key="m-1", text=body)


def a_template() -> MessageRequest:
    return MessageRequest(
        recipient_external_id="+971500000101",
        idempotency_key="t-1",
        template="vehicle_available",
        template_language="en",
        template_params={"1": "Karim", "2": "Hilux GR Sport"},
    )


def test_satisfies_the_protocol(pair: Pair) -> None:
    connector, _ = pair
    assert isinstance(connector, MessagingConnector)
    assert connector.platform
    assert connector.enforces_messaging_window is True


async def test_a_text_returns_an_external_id(pair: Pair) -> None:
    connector, _ = pair
    assert (await connector.send_message(a_text())).external_id


async def test_a_business_scoped_user_id_is_a_valid_recipient(pair: Pair) -> None:
    """Since 2026 a customer with a username may have no phone number at all."""
    connector, _ = pair
    result = await connector.send_message(a_text(recipient="AE.13491208655302741918"))
    assert result.external_id


async def test_an_empty_message_is_rejected_before_sending(pair: Pair) -> None:
    connector, _ = pair
    with pytest.raises(NotSupported):
        await connector.send_message(a_text(body=None))


async def test_a_closed_window_refuses_free_form_but_not_a_template(pair: Pair) -> None:
    connector, controls = pair
    controls.close_window()
    with pytest.raises(OutsideMessagingWindow):
        await connector.send_message(a_text())
    assert (await connector.send_message(a_template())).external_id


async def test_media_downloads_as_bytes_and_type(pair: Pair) -> None:
    connector, controls = pair
    controls.add_media("media-1", b"OggS voice", "audio/ogg")
    assert await connector.download_media("media-1") == (b"OggS voice", "audio/ogg")


async def test_unknown_media_is_rejected_not_retried(pair: Pair) -> None:
    connector, _ = pair
    with pytest.raises(RequestRejected):
        await connector.download_media("no-such-media")


async def test_templates_are_listed_in_our_vocabulary(pair: Pair) -> None:
    connector, controls = pair
    controls.add_template(TEMPLATE)
    [listed] = await connector.list_templates()
    assert (listed.name, listed.language, listed.category, listed.status) == (
        "vehicle_available",
        "en",
        "utility",
        "approved",
    )
    assert listed.components == TEMPLATE.components


async def test_an_expired_token_is_its_own_type(pair: Pair) -> None:
    """Not retryable: a person has to reconnect the channel."""
    connector, controls = pair
    controls.expire_token()
    with pytest.raises(TokenExpired):
        await connector.send_message(a_text())


async def test_a_rate_limit_carries_a_retry_hint(pair: Pair) -> None:
    connector, controls = pair
    controls.rate_limit(90)
    with pytest.raises(RateLimited) as exc:
        await connector.send_message(a_text())
    assert exc.value.retry_after_seconds == 90
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd apps/api && uv run pytest tests/connectors/test_messaging_contract.py -v`
Expected: FAIL — `ImportError: cannot import name 'MessagingConnector' from 'dealerai.connectors.base'`.

- [ ] **Step 3: Extend the contract**

In `apps/api/src/dealerai/connectors/base.py`, add after `OutsideMessagingWindow`:

```python
class RequestRejected(ConnectorError):
    """The platform refused the request itself: an unknown template, a media id
    that does not exist, an invalid recipient. The same request cannot succeed on
    a retry, so callers record the failure instead of retrying."""

    status = 422
    slug = "request-rejected"
    title = "The platform rejected the request"

    def __init__(self, detail: str | None = None, *, code: str = "unknown") -> None:
        super().__init__(detail)
        #: The platform's own error code, kept for the message's error field.
        self.code = code
```

In `MessageRequest`, add a last field:

```python
    #: The template's language code exactly as the platform stores it ("en_US", "ar").
    template_language: str | None = None
```

Add after `MessageResult`:

```python
@dataclass(frozen=True, slots=True)
class TemplateInfo:
    """A pre-approved message as the platform reports it, in our vocabulary."""

    external_id: str
    name: str
    language: str
    #: marketing | utility | authentication
    category: str
    #: approved | pending | rejected | paused | disabled
    status: str
    #: The platform's component list, verbatim: sending needs its exact shape.
    components: list[dict[str, Any]] = field(default_factory=list)
    rejected_reason: str | None = None
```

At the end of the file:

```python
@runtime_checkable
class MessagingConnector(Protocol):
    """A conversation channel: WhatsApp now, Instagram and Messenger messages later.

    Separate from SocialConnector because a messaging platform cannot publish, and
    a connector full of NotSupported stubs is a capability table in disguise.
    """

    platform: str
    enforces_messaging_window: bool

    async def send_message(self, req: MessageRequest) -> MessageResult: ...

    async def download_media(self, media_id: str) -> tuple[bytes, str]: ...

    async def list_templates(self) -> list[TemplateInfo]: ...
```

- [ ] **Step 4: Give the mock media and templates**

In `apps/api/src/dealerai/connectors/mock.py`, import `RequestRejected` and `TemplateInfo` from
`.base`, then add to `MockConnector`'s fields, after `comments`:

```python
    #: media id -> (bytes, mime), for download_media.
    media: dict[str, tuple[bytes, str]] = field(default_factory=dict)
    templates: list[TemplateInfo] = field(default_factory=list)
```

And to its methods, after `send_message`:

```python
    async def download_media(self, media_id: str) -> tuple[bytes, str]:
        self._maybe_fail()
        if media_id not in self.media:
            # What Meta answers for an id it does not know: code 100.
            raise RequestRejected(f"no media with id {media_id!r}", code="100")
        return self.media[media_id]

    async def list_templates(self) -> list[TemplateInfo]:
        self._maybe_fail()
        return list(self.templates)
```

- [ ] **Step 5: Run both contract suites**

Run: `cd apps/api && uv run pytest tests/connectors -v && uv run mypy src`
Expected: PASS — the new suite, and `test_contract.py` unchanged.

- [ ] **Step 6: Commit**

```bash
git add apps/api/src/dealerai/connectors/base.py apps/api/src/dealerai/connectors/mock.py apps/api/tests/connectors/test_messaging_contract.py
git commit -m "feat(sales): a contract for messaging connectors"
```

---

## Task 5: The WhatsApp Cloud API client

**Files:**
- Create: `apps/api/src/dealerai/connectors/whatsapp.py`
- Create: `apps/api/tests/connectors/fake_graph.py`
- Create: `apps/api/tests/connectors/test_whatsapp_cloud.py`
- Modify: `apps/api/tests/connectors/test_messaging_contract.py` (register the connector)

The fake Graph API answers the way Meta does — the same URLs, error codes and body shapes — so the
contract suite runs against the real client's HTTP and error mapping, with no network.
`tests/connectors` has no `__init__.py`, so pytest puts the directory on `sys.path` and
`import fake_graph` works from both test files.

- [ ] **Step 1: Write the fake Graph API**

```python
# apps/api/tests/connectors/fake_graph.py
"""A fake Graph API that answers like Meta, for the WhatsApp connector's tests."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx

from dealerai.connectors.base import TemplateInfo

VERSION = "v25.0"
PHONE_NUMBER_ID = "106540352242922"
WABA_ID = "102290129340398"
TOKEN = "EAAG-test-token"


def _error(status: int, code: int, message: str, **extra: Any) -> httpx.Response:
    return httpx.Response(
        status,
        json={"error": {"message": message, "type": "OAuthException", "code": code,
                        "fbtrace_id": "AbCdEfGh", **extra}},
    )


@dataclass
class FakeGraph:
    window_open: bool = True
    token_valid: bool = True
    rate_limited_for: int | None = None
    media: dict[str, tuple[bytes, str]] = field(default_factory=dict)
    #: Raw template objects, as the WABA would list them.
    templates: list[dict[str, Any]] = field(default_factory=list)
    requests: list[httpx.Request] = field(default_factory=list)
    sent: list[dict[str, Any]] = field(default_factory=list)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not self.token_valid or request.headers.get("Authorization") != f"Bearer {TOKEN}":
            return _error(401, 190, "Error validating access token: Session has expired.")
        if self.rate_limited_for is not None:
            response = _error(400, 130429, "Rate limit hit")
            response.headers["Retry-After"] = str(self.rate_limited_for)
            return response

        if request.url.host == "lookaside.fbsbx.com":
            data, mime = self.media[request.url.params["mid"]]
            return httpx.Response(200, content=data, headers={"Content-Type": mime})

        path = request.url.path
        if request.method == "POST" and path == f"/{VERSION}/{PHONE_NUMBER_ID}/messages":
            body = json.loads(request.content)
            self.sent.append(body)
            if body["type"] != "template" and not self.window_open:
                return _error(
                    400, 131047, "Re-engagement message",
                    error_data={"details": "Message failed to send because more than 24 hours "
                                           "have passed since the customer last replied."},
                )
            recipient = body.get("to") or body.get("recipient")
            return httpx.Response(200, json={
                "messaging_product": "whatsapp",
                "contacts": [{"input": recipient, "wa_id": recipient}],
                "messages": [{"id": f"wamid.FAKE{len(self.sent)}"}],
            })

        if request.method == "GET" and path == f"/{VERSION}/{WABA_ID}/message_templates":
            index = int(request.url.params.get("after", "0"))
            page: dict[str, Any] = {"data": self.templates[index:index + 1]}
            if index + 1 < len(self.templates):
                page["paging"] = {"next": f"https://graph.facebook.com/{VERSION}/{WABA_ID}"
                                          f"/message_templates?after={index + 1}"}
            return httpx.Response(200, json=page)

        media_id = path.rsplit("/", 1)[-1]
        if request.method == "GET" and media_id in self.media:
            data, mime = self.media[media_id]
            return httpx.Response(200, json={
                "url": f"https://lookaside.fbsbx.com/whatsapp_business/attachments/?mid={media_id}",
                "mime_type": mime, "sha256": "0" * 64, "file_size": len(data), "id": media_id,
                "messaging_product": "whatsapp",
            })

        return _error(400, 100, "Unsupported get request. Object with ID does not exist.")


@dataclass
class CloudControls:
    """The contract suite's Controls, for a connector talking to FakeGraph."""

    graph: FakeGraph

    def close_window(self) -> None:
        self.graph.window_open = False

    def expire_token(self) -> None:
        self.graph.token_valid = False

    def rate_limit(self, retry_after_seconds: int) -> None:
        self.graph.rate_limited_for = retry_after_seconds

    def add_media(self, media_id: str, data: bytes, mime: str) -> None:
        self.graph.media[media_id] = (data, mime)

    def add_template(self, template: TemplateInfo) -> None:
        self.graph.templates.append({
            "id": template.external_id, "name": template.name, "language": template.language,
            "category": template.category.upper(), "status": template.status.upper(),
            "components": template.components,
        })
```

- [ ] **Step 2: Register the connector with the contract suite, and write its own tests**

In `apps/api/tests/connectors/test_messaging_contract.py`, add to the imports:

```python
import httpx
from fake_graph import PHONE_NUMBER_ID, TOKEN, WABA_ID, CloudControls, FakeGraph

from dealerai.connectors.whatsapp import WhatsAppCloud
```

and replace `FACTORIES` with:

```python
def _cloud() -> tuple[MessagingConnector, Controls]:
    graph = FakeGraph()
    connector = WhatsAppCloud(
        phone_number_id=PHONE_NUMBER_ID,
        waba_id=WABA_ID,
        access_token=TOKEN,
        graph_version="v25.0",
        transport=httpx.MockTransport(graph),
    )
    return connector, CloudControls(graph)


FACTORIES: list[tuple[str, Callable[[], tuple[MessagingConnector, Controls]]]] = [
    ("mock_whatsapp", _mock),
    ("whatsapp_cloud", _cloud),
]
```

```python
# apps/api/tests/connectors/test_whatsapp_cloud.py
"""What only the Cloud API client can get wrong: Meta's request shapes and error codes."""

from __future__ import annotations

import json

import httpx
import pytest
from fake_graph import PHONE_NUMBER_ID, TOKEN, WABA_ID, FakeGraph

from dealerai.connectors.base import (
    ConnectorError,
    MessageRequest,
    NotSupported,
    OutsideMessagingWindow,
    RequestRejected,
)
from dealerai.connectors.whatsapp import WhatsAppCloud, template_status


def _connector(graph: FakeGraph | httpx.MockTransport) -> WhatsAppCloud:
    transport = graph if isinstance(graph, httpx.MockTransport) else httpx.MockTransport(graph)
    return WhatsAppCloud(
        phone_number_id=PHONE_NUMBER_ID,
        waba_id=WABA_ID,
        access_token=TOKEN,
        graph_version="v25.0",
        transport=transport,
    )


async def test_a_text_has_meta_s_shape() -> None:
    graph = FakeGraph()
    await _connector(graph).send_message(
        MessageRequest(recipient_external_id="+971500000101", idempotency_key="k", text="Hello")
    )
    assert graph.sent == [{
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": "+971500000101",
        "type": "text",
        "text": {"body": "Hello", "preview_url": False},
    }]
    assert graph.requests[0].url.path == f"/v25.0/{PHONE_NUMBER_ID}/messages"


async def test_a_business_scoped_user_id_goes_in_recipient() -> None:
    graph = FakeGraph()
    await _connector(graph).send_message(
        MessageRequest(recipient_external_id="AE.1349120865530274", idempotency_key="k", text="Hi")
    )
    assert graph.sent[0]["recipient"] == "AE.1349120865530274"
    assert "to" not in graph.sent[0]


async def test_template_parameters_are_sent_in_numeric_order() -> None:
    graph = FakeGraph()
    params = {str(n): f"value {n}" for n in (10, 2, 1, 3, 4, 5, 6, 7, 8, 9)}
    await _connector(graph).send_message(MessageRequest(
        recipient_external_id="+971500000101", idempotency_key="k",
        template="price_update", template_language="en_US", template_params=params,
    ))
    template = graph.sent[0]["template"]
    assert template["name"] == "price_update"
    assert template["language"] == {"code": "en_US"}
    [body] = template["components"]
    assert [p["text"] for p in body["parameters"]] == [f"value {n}" for n in range(1, 11)]


async def test_a_template_without_its_language_is_refused() -> None:
    with pytest.raises(NotSupported):
        await _connector(FakeGraph()).send_message(MessageRequest(
            recipient_external_id="+971500000101", idempotency_key="k", template="price_update",
        ))


async def test_meta_s_explanation_reaches_the_error() -> None:
    graph = FakeGraph(window_open=False)
    with pytest.raises(OutsideMessagingWindow) as exc:
        await _connector(graph).send_message(
            MessageRequest(recipient_external_id="+971500000101", idempotency_key="k", text="Hi")
        )
    assert "24 hours" in str(exc.value.detail)


async def test_a_rejection_keeps_meta_s_code() -> None:
    with pytest.raises(RequestRejected) as exc:
        await _connector(FakeGraph()).download_media("missing")
    assert exc.value.code == "100"


async def test_server_errors_and_network_failures_are_not_rejections() -> None:
    """The send handler must not mark a message failed when Meta may have sent it."""
    server_error = httpx.MockTransport(lambda _: httpx.Response(500, text="oops"))
    with pytest.raises(ConnectorError) as exc:
        await _connector(server_error).download_media("m")
    assert type(exc.value) is ConnectorError

    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(ConnectorError) as exc:
        await _connector(httpx.MockTransport(unreachable)).send_message(
            MessageRequest(recipient_external_id="+971500000101", idempotency_key="k", text="Hi")
        )
    assert type(exc.value) is ConnectorError


async def test_media_download_sends_the_token_to_the_file_host_too() -> None:
    graph = FakeGraph(media={"media-1": (b"OggS", "audio/ogg")})
    assert await _connector(graph).download_media("media-1") == (b"OggS", "audio/ogg")
    file_request = graph.requests[-1]
    assert file_request.url.host == "lookaside.fbsbx.com"
    assert file_request.headers["Authorization"] == f"Bearer {TOKEN}"


async def test_templates_follow_pagination_in_our_vocabulary() -> None:
    graph = FakeGraph(templates=[
        {"id": "1", "name": "vehicle_available", "language": "en_US", "category": "UTILITY",
         "status": "APPROVED", "components": [{"type": "BODY", "text": "Hi {{1}}"}]},
        {"id": "2", "name": "new_arrivals", "language": "ar", "category": "MARKETING",
         "status": "REJECTED", "rejected_reason": "INVALID_FORMAT", "components": []},
    ])
    first, second = await _connector(graph).list_templates()
    assert (first.name, first.language, first.category, first.status, first.rejected_reason) == (
        "vehicle_available", "en_US", "utility", "approved", None)
    assert (second.category, second.status, second.rejected_reason) == (
        "marketing", "rejected", "INVALID_FORMAT")
    assert len(graph.requests) == 2, "the second page was not requested"
    assert json.loads(json.dumps(first.components)) == [{"type": "BODY", "text": "Hi {{1}}"}]


@pytest.mark.parametrize(
    ("event", "expected"),
    [("APPROVED", "approved"), ("REINSTATED", "approved"), ("IN_APPEAL", "pending"),
     ("REJECTED", "rejected"), ("PAUSED", "paused"), ("DISABLED", "disabled"),
     ("PENDING_DELETION", "disabled"), (None, "disabled")],
)
def test_template_status_in_our_vocabulary(event: str | None, expected: str) -> None:
    assert template_status(event) == expected
```

- [ ] **Step 3: Run them to verify they fail**

Run: `cd apps/api && uv run pytest tests/connectors -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dealerai.connectors.whatsapp'`.

- [ ] **Step 4: Write the client**

```python
# apps/api/src/dealerai/connectors/whatsapp.py
"""WhatsApp Cloud API: the messaging connector for one WhatsApp number.

Everything Meta-shaped lives in this file — Graph URLs, error codes, payload
layouts — so handlers speak only the contract in base.py.
"""

from __future__ import annotations

from typing import Any

import httpx

from .base import (
    ConnectorError,
    MessageRequest,
    MessageResult,
    NotSupported,
    OutsideMessagingWindow,
    RateLimited,
    RequestRejected,
    TemplateInfo,
    TokenExpired,
)

GRAPH_URL = "https://graph.facebook.com"

#: Meta error codes a caller branches on. Any other 4xx is a RequestRejected
#: carrying Meta's own explanation.
_TOKEN_CODES = frozenset({190})
_RATE_LIMIT_CODES = frozenset({4, 80007, 130429, 131056})
_WINDOW_CODES = frozenset({131047})

_TEMPLATE_STATUSES = {
    "APPROVED": "approved",
    "REINSTATED": "approved",
    "FLAGGED": "approved",
    "PENDING": "pending",
    "IN_APPEAL": "pending",
    "REJECTED": "rejected",
    "PAUSED": "paused",
}
_TEMPLATE_CATEGORIES = {
    "MARKETING": "marketing",
    "UTILITY": "utility",
    "AUTHENTICATION": "authentication",
}


def template_status(raw: str | None) -> str:
    """A template status or status-webhook event in our vocabulary. Anything
    unrecognised — DISABLED, PENDING_DELETION, LIMIT_EXCEEDED — is not sendable."""
    return _TEMPLATE_STATUSES.get((raw or "").upper(), "disabled")


def _template(raw: dict[str, Any]) -> TemplateInfo:
    reason = raw.get("rejected_reason")
    return TemplateInfo(
        external_id=str(raw["id"]),
        name=str(raw["name"]),
        language=str(raw["language"]),
        # An unknown category is treated as marketing: the one that needs consent.
        category=_TEMPLATE_CATEGORIES.get(str(raw.get("category", "")).upper(), "marketing"),
        status=template_status(raw.get("status")),
        components=list(raw.get("components") or []),
        rejected_reason=None if reason in (None, "", "NONE") else str(reason),
    )


def _retry_after(response: httpx.Response) -> int:
    value = response.headers.get("Retry-After", "")
    return int(value) if value.isdigit() else 60


def _error(response: httpx.Response) -> ConnectorError:
    try:
        body = response.json()
    except ValueError:
        body = None
    error = body.get("error") if isinstance(body, dict) else None
    error = error if isinstance(error, dict) else {}
    code = error.get("code")
    details = (error.get("error_data") or {}).get("details")
    detail = str(details or error.get("message") or response.text[:300] or response.status_code)

    if code in _TOKEN_CODES or response.status_code == 401:
        return TokenExpired(detail)
    if code in _RATE_LIMIT_CODES or response.status_code == 429:
        return RateLimited(detail, retry_after_seconds=_retry_after(response))
    if code in _WINDOW_CODES:
        return OutsideMessagingWindow(detail)
    if response.status_code >= 500:
        # Not a rejection: Meta may have done the work. The caller must not assume it failed.
        return ConnectorError(detail)
    return RequestRejected(detail, code=str(code or response.status_code))


class WhatsAppCloud:
    platform = "whatsapp"
    enforces_messaging_window = True

    def __init__(
        self,
        *,
        phone_number_id: str,
        waba_id: str | None,
        access_token: str,
        graph_version: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._phone_number_id = phone_number_id
        self._waba_id = waba_id
        self._token = access_token
        self._base_url = f"{GRAPH_URL}/{graph_version}"
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        # The token goes to every host, lookaside.fbsbx.com included: media files need it.
        return httpx.AsyncClient(
            base_url=self._base_url,
            headers={"Authorization": f"Bearer {self._token}"},
            timeout=httpx.Timeout(30.0, connect=10.0),
            transport=self._transport,
        )

    @staticmethod
    async def _call(
        client: httpx.AsyncClient, method: str, url: str, **kwargs: Any
    ) -> httpx.Response:
        try:
            response = await client.request(method, url, **kwargs)
        except httpx.TransportError as exc:
            raise ConnectorError(f"could not reach the WhatsApp Cloud API: {exc}") from exc
        if not response.is_success:
            raise _error(response)
        return response

    async def send_message(self, req: MessageRequest) -> MessageResult:
        if not req.text and not req.template:
            raise NotSupported("a message needs either text or a template")

        body: dict[str, Any] = {"messaging_product": "whatsapp", "recipient_type": "individual"}
        # A phone number goes in `to`; a business-scoped user id ("AE.1349…") in `recipient`.
        recipient_field = "to" if req.recipient_external_id.startswith("+") else "recipient"
        body[recipient_field] = req.recipient_external_id

        if req.template:
            if not req.template_language:
                raise NotSupported("a template send needs the template's language code")
            template: dict[str, Any] = {
                "name": req.template,
                "language": {"code": req.template_language},
            }
            if req.template_params:
                ordered = [req.template_params[k] for k in sorted(req.template_params, key=int)]
                template["components"] = [
                    {"type": "body", "parameters": [{"type": "text", "text": v} for v in ordered]}
                ]
            body |= {"type": "template", "template": template}
        else:
            body |= {"type": "text", "text": {"body": req.text, "preview_url": False}}

        async with self._client() as client:
            response = await self._call(
                client, "POST", f"/{self._phone_number_id}/messages", json=body
            )
        return MessageResult(external_id=str(response.json()["messages"][0]["id"]))

    async def download_media(self, media_id: str) -> tuple[bytes, str]:
        async with self._client() as client:
            meta = (await self._call(client, "GET", f"/{media_id}")).json()
            # The URL lives for minutes, which is why this runs in the worker right away.
            file = await self._call(client, "GET", str(meta["url"]))
        mime = meta.get("mime_type") or file.headers.get("Content-Type", "application/octet-stream")
        return file.content, str(mime)

    async def list_templates(self) -> list[TemplateInfo]:
        if not self._waba_id:
            raise NotSupported("listing templates needs the WhatsApp Business Account id")
        url: str | None = f"/{self._waba_id}/message_templates"
        params: dict[str, str] | None = {
            "fields": "id,name,language,category,status,components,rejected_reason",
            "limit": "100",
        }
        templates: list[TemplateInfo] = []
        async with self._client() as client:
            while url:
                page = (await self._call(client, "GET", url, params=params)).json()
                templates += [_template(raw) for raw in page.get("data", [])]
                url = (page.get("paging") or {}).get("next")
                params = None  # the next link carries its own query
        return templates
```

- [ ] **Step 5: Run the tests**

Run: `cd apps/api && uv run pytest tests/connectors -v && uv run mypy src && uv run ruff check . && uv run ruff format --check .`
Expected: PASS — the contract suite now runs twice (`mock_whatsapp`, `whatsapp_cloud`); mypy,
ruff and format clean. If `ruff format --check` flags the fake's compact literals, run
`uv run ruff format tests/connectors` and re-run.

- [ ] **Step 6: Commit**

```bash
git add apps/api/src/dealerai/connectors/whatsapp.py apps/api/tests/connectors
git commit -m "feat(sales): WhatsApp Cloud API connector"
```

---
