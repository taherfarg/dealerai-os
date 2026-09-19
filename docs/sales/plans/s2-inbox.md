# Sales S2 — Inbox Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** a salesperson answers a waiting customer end to end in the browser — sees the queue, opens
the thread, reads the voice note's transcript, replies, and watches the waiting timer stop — while a
manager sees the same conversation, its timer, and who it is assigned to.

**Architecture:** the API grows read endpoints over the conversations S1 already fills, plus the
actions a thread needs (assign, close, note, read cursor). Assignment and response targets become
worker handlers on the existing queue, with the sweep rescheduling itself instead of a new scheduler.
Live updates travel `trigger → pg_notify('rt') → one LISTEN per API process → SSE → React Query
invalidation`; the payload carries ids only, so a missed event costs a refetch and never shows a
wrong screen. Message media is fetched through short-lived signed links the API issues, so stored
objects stay private and an `<img src>` still works.

**Tech stack:** Postgres 17 (LISTEN/NOTIFY, triggers, full-text `simple`) · asyncpg · FastAPI
(StreamingResponse) · Next.js 16 · React 19 · TanStack Query · Tailwind v4 · Vitest · pytest.

**Before you start:**

- Docker Desktop running; prefix database commands with `COMPOSE_PROJECT_NAME=dealeraios` in this
  worktree. Run checks with `set -o pipefail`. Never run two pytest sessions at once — they share
  the local database and wipe each other's tenants.
- Branch `sales/phase-1`. `.env` already carries `WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN`,
  `WHATSAPP_GRAPH_VERSION` and `STORAGE_DIR=.storage`.
- Read [../08-screens.md](../08-screens.md) §2–§4 (the three screens this slice builds),
  [../06-api-contract.md](../06-api-contract.md) §3 (the routes), [../05-workflows.md](../05-workflows.md)
  §5 (assignment and response targets) and [../01-architecture.md](../01-architecture.md) §2 B (live
  updates). They are the specification; this plan implements them.
- **The lesson S1 left:** a green suite is not a working feature. Every S1 defect — a dead demo
  path, a double-send risk, a queue full of dead letters — sat behind 787 passing tests
  ([s1-whatsapp.md](s1-whatsapp.md) § Review). Task 14 runs this slice's exit path in a browser
  before anyone calls it done.

---

## What this slice does not build

| Item | Arrives with |
|---|---|
| AI drafts, the draft panel, `GET /v1/conversations/{id}/suggestion` | S4 |
| Customer 360, reassign, merge, pipelines, leads, tasks | S3 |
| Quick replies, settings screens, the manager dashboard and daily brief | S6 |
| Web Push, the installable app, `push_subscriptions` | S7 |
| Outbound attachments and `POST /v1/uploads`, voice notes recorded in the browser | S7 (Phase 2 in [03](../03-whatsapp.md) §7) |
| Coexistence echoes shown as "Sent from phone" are **already ingested** (S1) and only need rendering here | — |

---

## File structure

| File | Responsibility |
|---|---|
| `supabase/migrations/0008_sales_inbox.sql` | **Create.** `conversation_reads`, `notifications`, live-update triggers, inbox and search indexes |
| `apps/api/src/dealerai/sales/settings.py` | **Create.** `SalesSettings` — the validated shape of `tenants.sales_settings` |
| `apps/api/src/dealerai/sales/hours.py` | **Create.** Business-hours arithmetic: when a reply is due, in the tenant's timezone |
| `apps/api/src/dealerai/sales/assignment.py` | **Create.** Pure routing choice: rules → team → the member who takes it |
| `apps/api/src/dealerai/events/handlers/inbox.py` | **Create.** Assignment, notifications, the response-target sweep |
| `apps/api/src/dealerai/events/handlers/parked.py` | **Modify.** Remove the four types this slice takes over |
| `apps/api/src/dealerai/db/queries/inbox.py` | **Create.** The list, counts and thread SQL, in one place |
| `apps/api/src/dealerai/routes/inbox.py` | **Modify.** List, counts, detail, messages, notes, assign, status, read |
| `apps/api/src/dealerai/routes/notifications.py` | **Create.** `GET /v1/notifications`, `POST /v1/notifications/read` |
| `apps/api/src/dealerai/routes/stream.py` | **Create.** `GET /v1/stream`, the SSE endpoint |
| `apps/api/src/dealerai/realtime.py` | **Create.** One LISTEN connection per process, fan-out to open streams |
| `apps/api/src/dealerai/media/links.py`, `routes/media.py` | **Create.** Signed, short-lived media links |
| `apps/web/lib/api/{keys,hooks}.ts` | **Modify.** Inbox queries, optimistic send and assign |
| `apps/web/lib/live.tsx` | **Create.** `useLiveEvents()` — the SSE reader and what each event invalidates |
| `apps/web/app/[tenant]/inbox/page.tsx`, `[conversationId]/page.tsx`, `layout.tsx` | **Create/modify.** The list, the thread, the two-pane desktop layout |
| `apps/web/components/inbox/*` | **Create.** Row, filters, thread messages, composer, assignment control, window banner |
| `apps/web/messages/{en,ar}.ts` | **Modify.** Every string this slice shows |

---

## Task 1: The tables and triggers the inbox reads

**Files:**
- Create: `supabase/migrations/0008_sales_inbox.sql`
- Create: `apps/api/tests/test_inbox_schema.py`

`conversation_reads` is one row per person per conversation, so an unread count is "inbound messages
newer than my cursor" rather than a flag per message. `notifications` carries its own dedupe key
because the queue only dedupes events that are still pending: "tell the manager once" has to survive
the first event finishing.

The triggers are what make live updates impossible to forget — a new write path gets them for free,
and bulk imports turn them off with `set local app.suppress_rt = 'on'`.

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/test_inbox_schema.py
"""What 0008_sales_inbox.sql must be true about: reads, notifications, live updates."""

from __future__ import annotations

import asyncio
import json
import uuid

import asyncpg
import pytest

from conftest import TENANT_A, USER_A


async def _conversation(su: asyncpg.Connection) -> uuid.UUID:
    return await su.fetchval("select id from conversations where tenant_id = $1", TENANT_A)


async def test_a_read_cursor_is_one_row_per_person(
    su: asyncpg.Connection, seeded: None
) -> None:
    conversation_id = await _conversation(su)
    insert = """insert into conversation_reads (tenant_id, conversation_id, user_id, last_read_at)
                values ($1, $2, $3, now())
                on conflict (conversation_id, user_id) do update set last_read_at = excluded.last_read_at"""
    await su.execute(insert, TENANT_A, conversation_id, USER_A)
    await su.execute(insert, TENANT_A, conversation_id, USER_A)
    assert (
        await su.fetchval(
            "select count(*) from conversation_reads where conversation_id = $1", conversation_id
        )
        == 1
    )


async def test_a_notification_is_delivered_once(su: asyncpg.Connection, seeded: None) -> None:
    """"Tell the manager this conversation is late" must not fire twice for the
    same waiting period, and the queue only dedupes events that are still pending."""
    insert = """insert into notifications (tenant_id, user_id, kind, title, dedupe_key)
                values ($1, $2, 'waiting_missed', 'Karim has been waiting', 'sla:1:missed')
                on conflict do nothing"""
    await su.execute(insert, TENANT_A, USER_A)
    await su.execute(insert, TENANT_A, USER_A)
    assert await su.fetchval("select count(*) from notifications") == 1


async def test_a_notification_belongs_to_one_person(
    db: None, su: asyncpg.Connection, seeded: None
) -> None:
    from dealerai.db.session import tenant_session

    await su.execute(
        """insert into notifications (tenant_id, user_id, kind, title)
           values ($1, $2, 'assigned', 'For you')""",
        TENANT_A,
        USER_A,
    )
    other = uuid.UUID("eeeeeeee-1111-4000-8000-000000000001")
    await su.execute("insert into auth.users (id, email) values ($1, 'other@test')", other)
    await su.execute(
        "insert into memberships (tenant_id, user_id, role) values ($1, $2, 'sales')",
        TENANT_A,
        other,
    )
    try:
        async with tenant_session(TENANT_A, user_id=other, scope="own") as conn:
            assert await conn.fetchval("select count(*) from notifications") == 0
        async with tenant_session(TENANT_A, user_id=USER_A, scope="own") as conn:
            assert await conn.fetchval("select count(*) from notifications") == 1
    finally:
        await su.execute("delete from auth.users where id = $1", other)


def _collector(queue: asyncio.Queue[str]):  # type: ignore[no-untyped-def]
    """A named callback, so remove_listener can actually remove it."""

    def listener(*args: object) -> None:
        queue.put_nowait(str(args[-1]))

    return listener


async def test_a_new_message_announces_itself(su: asyncpg.Connection, seeded: None) -> None:
    """The trigger is what makes a live update impossible to forget."""
    conversation_id = await _conversation(su)
    queue: asyncio.Queue[str] = asyncio.Queue()
    listener = _collector(queue)
    await su.add_listener("rt", listener)
    try:
        await su.execute(
            """insert into messages (tenant_id, conversation_id, direction, sender, origin, body)
               values ($1, $2, 'in', 'customer', 'customer', 'live update please')""",
            TENANT_A,
            conversation_id,
        )
        payload = json.loads(await asyncio.wait_for(queue.get(), timeout=5))
    finally:
        await su.remove_listener("rt", listener)

    assert payload["type"] == "message.created"
    assert payload["tenant_id"] == str(TENANT_A)
    assert payload["conversation_id"] == str(conversation_id)
    # The message carries its conversation's visibility, so the stream can filter
    # without a query per event.
    assert "owner_id" in payload and "assigned_to" in payload and "team_id" in payload


async def test_a_bulk_import_can_stay_quiet(su: asyncpg.Connection, seeded: None) -> None:
    """The history import writes thousands of rows; one notification each would
    flood the queue and the browser."""
    conversation_id = await _conversation(su)
    queue: asyncio.Queue[str] = asyncio.Queue()
    listener = _collector(queue)
    await su.add_listener("rt", listener)
    try:
        async with su.transaction():
            await su.execute("select set_config('app.suppress_rt', 'on', true)")
            await su.execute(
                """insert into messages (tenant_id, conversation_id, direction, sender, origin,
                                         body)
                   values ($1, $2, 'in', 'customer', 'history', 'imported')""",
                TENANT_A,
                conversation_id,
            )
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(queue.get(), timeout=1)
    finally:
        await su.remove_listener("rt", listener)


async def test_search_reads_the_transcript_too(su: asyncpg.Connection, seeded: None) -> None:
    """A customer's voice note is searchable by what was said in it."""
    conversation_id = await _conversation(su)
    await su.execute(
        """insert into messages (tenant_id, conversation_id, direction, sender, origin, type,
                                 transcript)
           values ($1, $2, 'in', 'customer', 'customer', 'audio',
                   '{"text": "is the land cruiser still available", "language": "en"}'::jsonb)""",
        TENANT_A,
        conversation_id,
    )
    found = await su.fetchval(
        """select count(*) from messages
           where tenant_id = $1
             and to_tsvector('simple', coalesce(body, '') || ' ' ||
                             coalesce(transcript->>'text', '')) @@ plainto_tsquery('simple', $2)""",
        TENANT_A,
        "land cruiser",
    )
    assert found == 1
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd apps/api && uv run pytest tests/test_inbox_schema.py -v`
Expected: FAIL — `relation "conversation_reads" does not exist`.

- [ ] **Step 3: Write the migration**

```sql
-- supabase/migrations/0008_sales_inbox.sql
-- =============================================================================
-- 0008_sales_inbox — Sales S2: read cursors, notifications and live updates.
-- See docs/sales/02-data-model.md § 2 and § 5.
-- =============================================================================

-- =============================================================================
-- WHO HAS READ WHAT
-- One row per person per conversation. An unread count is then "inbound
-- messages newer than my cursor" — not a flag per message, which would be a
-- row per person per message.
-- =============================================================================
create table conversation_reads (
  tenant_id       uuid not null references tenants(id) on delete cascade,
  conversation_id uuid not null references conversations(id) on delete cascade,
  user_id         uuid not null references auth.users(id) on delete cascade,
  last_read_at    timestamptz not null default now(),
  primary key (conversation_id, user_id)
);
create index on conversation_reads (tenant_id, user_id);

-- =============================================================================
-- NOTIFICATIONS
-- dedupe_key is what makes "once" true: the event queue only dedupes events
-- that are still pending, so a sweep that runs every minute would otherwise
-- tell the manager again the moment the first event finished.
-- =============================================================================
create table notifications (
  id         uuid primary key default gen_random_uuid(),
  tenant_id  uuid not null references tenants(id) on delete cascade,
  user_id    uuid not null references auth.users(id) on delete cascade,
  kind       text not null check (kind in
               ('message_received', 'assigned', 'waiting_due_soon', 'waiting_missed',
                'unassigned_waiting', 'template_rejected', 'channel_disconnected',
                'channel_quality')),
  title      text not null,
  body       text,
  href       text,
  entity     jsonb not null default '{}'::jsonb,
  dedupe_key text,
  read_at    timestamptz,
  created_at timestamptz not null default now()
);
create index on notifications (tenant_id, user_id, created_at desc);
create index on notifications (tenant_id, user_id) where read_at is null;
create unique index notifications_dedupe_uq on notifications (tenant_id, user_id, dedupe_key)
  where dedupe_key is not null;

-- Both tables are the caller's own rows, never a colleague's. WITH CHECK stays
-- tenant-only: the worker writes notifications for other people.
do $$
declare t text;
begin
  foreach t in array array['conversation_reads', 'notifications']
  loop
    execute format('alter table %I enable row level security', t);
    execute format('alter table %I force row level security', t);
    execute format(
      'create policy own_rows on %I
         using (app.has_tenant_access(tenant_id)
                and (user_id = (select app.current_user_id())
                     or (select app.current_user_id()) is null))
         with check (app.has_tenant_access(tenant_id))', t);
    execute format('revoke all on %I from anon, authenticated', t);
  end loop;
end $$;

-- =============================================================================
-- INDEXES THE INBOX QUERIES NEED (docs/sales/02-data-model.md § 6)
-- =============================================================================
create index on conversations (tenant_id, assigned_to, status, last_message_at desc);
create index on conversations (tenant_id, status, last_message_at desc)
  where assigned_to is null;

-- One index for search across three languages. `simple`, not english: a tenant's
-- messages mix Arabic, English and French, and stemming for one mangles the others.
create index messages_search_idx on messages using gin (
  to_tsvector('simple', coalesce(body, '') || ' ' || coalesce(transcript->>'text', ''))
);

-- =============================================================================
-- LIVE UPDATES
-- A trigger, not a call in each write path: a path added later cannot forget it.
-- The payload is ids plus the visibility columns the stream filters on — never
-- content, which would put customer messages in the Postgres notification queue.
-- =============================================================================
create or replace function app.notify_rt()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  row_json jsonb := to_jsonb(new);
  conversation conversations%rowtype;
  payload jsonb;
begin
  -- Bulk work (the history import) sets this and emits one summary itself.
  if coalesce(current_setting('app.suppress_rt', true), '') = 'on' then
    return null;
  end if;

  if tg_table_name = 'messages' then
    select * into conversation from conversations c where c.id = new.conversation_id;
  elsif tg_table_name = 'conversations' then
    conversation := new;
  end if;

  payload := jsonb_build_object(
    'tenant_id', row_json->>'tenant_id',
    'type', tg_argv[0],
    'id', row_json->>'id',
    'conversation_id', coalesce(row_json->>'conversation_id', conversation.id::text),
    'owner_id', conversation.owner_id,
    'assigned_to', conversation.assigned_to,
    'team_id', conversation.team_id,
    'user_id', row_json->>'user_id'
  );
  perform pg_notify('rt', payload::text);
  return null;
end $$;

revoke all on function app.notify_rt() from public;

create trigger conversations_rt after insert or update on conversations
  for each row execute function app.notify_rt('conversation.updated');
create trigger messages_rt_insert after insert on messages
  for each row execute function app.notify_rt('message.created');
create trigger messages_rt_update after update on messages
  for each row execute function app.notify_rt('message.updated');
create trigger notifications_rt after insert on notifications
  for each row execute function app.notify_rt('notification.created');
```

- [ ] **Step 4: Run the tests**

Run: `cd apps/api && uv run pytest tests/test_inbox_schema.py tests/test_tenant_isolation.py tests/test_visibility.py -v`
Expected: PASS, including the structural tests that now cover two more tables.

Then the whole suite: `set -o pipefail; npm run test 2>&1 | tail -3`.

- [ ] **Step 5: Commit**

```bash
git add supabase/migrations/0008_sales_inbox.sql apps/api/tests/test_inbox_schema.py
git commit -m "feat(sales): read cursors, notifications and live-update triggers"
```

---

## Task 2: When a reply is actually due

**Files:**
- Create: `apps/api/src/dealerai/sales/settings.py`
- Create: `apps/api/src/dealerai/sales/hours.py`
- Create: `apps/api/tests/test_sales_hours.py`
- Modify: `apps/api/pyproject.toml` (`tzdata`)

A customer who writes at 23:30 is not late five minutes later. The response target counts business
minutes in the tenant's own timezone, which is the difference between a dashboard a manager trusts
and one they learn to ignore.

`zoneinfo` needs the IANA database, which Windows does not ship — hence `tzdata`, a pure-data
package with no code.

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/test_sales_hours.py
"""Response targets count business minutes, in the tenant's timezone. No database."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from dealerai.sales.hours import due_at, is_open
from dealerai.sales.settings import SalesSettings

DUBAI = ZoneInfo("Asia/Dubai")
#: Pollux: open every day but Sunday, 09:00–19:00, with a short Saturday.
SETTINGS = SalesSettings.model_validate(
    {
        "first_response_target_min": 5,
        "business_hours": {
            "mon": {"open": "09:00", "close": "19:00"},
            "tue": {"open": "09:00", "close": "19:00"},
            "wed": {"open": "09:00", "close": "19:00"},
            "thu": {"open": "09:00", "close": "19:00"},
            "fri": {"open": "09:00", "close": "19:00"},
            "sat": {"open": "10:00", "close": "14:00"},
        },
    }
)


def dubai(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=DUBAI)


def test_inside_business_hours_the_target_is_just_minutes() -> None:
    due = due_at(dubai("2026-09-16T10:00"), settings=SETTINGS, tz=DUBAI)
    assert due == dubai("2026-09-16T10:05")


def test_a_message_at_night_is_due_after_opening() -> None:
    """The whole point: 23:30 is not late at 23:35."""
    due = due_at(dubai("2026-09-16T23:30"), settings=SETTINGS, tz=DUBAI)
    assert due == dubai("2026-09-17T09:05")


def test_minutes_left_at_closing_continue_the_next_morning() -> None:
    due = due_at(dubai("2026-09-16T18:58"), settings=SETTINGS, tz=DUBAI)
    assert due == dubai("2026-09-17T09:03")


def test_a_closed_day_is_skipped() -> None:
    saturday_evening = dubai("2026-09-19T15:00")  # after Saturday's 14:00 close
    assert due_at(saturday_evening, settings=SETTINGS, tz=DUBAI) == dubai("2026-09-21T09:05")


def test_a_tenant_that_never_closes_uses_the_clock() -> None:
    always = SalesSettings.model_validate({"first_response_target_min": 5, "business_hours": {}})
    moment = dubai("2026-09-19T03:00")
    assert due_at(moment, settings=always, tz=DUBAI) == dubai("2026-09-19T03:05")


@pytest.mark.parametrize(
    ("moment", "expected"),
    [("2026-09-16T10:00", True), ("2026-09-16T08:59", False), ("2026-09-20T11:00", False)],
)
def test_is_open_answers_for_the_tenants_week(moment: str, expected: bool) -> None:
    assert is_open(dubai(moment), settings=SETTINGS, tz=DUBAI) is expected


def test_settings_survive_a_key_it_has_never_seen() -> None:
    """sales_settings is read whole; a newer key must not break an older API."""
    settings = SalesSettings.model_validate({"invented_later": 3, "first_response_target_min": 7})
    assert settings.first_response_target_min == 7
    assert settings.unassigned_visible_to_sales is True


def test_an_impossible_target_is_rejected_at_the_edge() -> None:
    with pytest.raises(ValueError):
        SalesSettings.model_validate({"first_response_target_min": 0})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd apps/api && uv run pytest tests/test_sales_hours.py -v`
Expected: FAIL — `No module named 'dealerai.sales.settings'`.

- [ ] **Step 3: Write the settings model**

```python
# apps/api/src/dealerai/sales/settings.py
"""The validated shape of tenants.sales_settings.

The column is jsonb and is read whole, never filtered on (docs/03-database-schema.md § 3).
This is where it becomes typed, once, at the edge — and `extra="ignore"` is deliberate:
a staging deploy writing a key this version has never seen must not break it.
"""

from __future__ import annotations

from datetime import time
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WEEKDAYS: tuple[Weekday, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


class OpenHours(BaseModel):
    model_config = ConfigDict(extra="ignore")

    open: time
    close: time

    @field_validator("close")
    @classmethod
    def _after_open(cls, value: time, info: object) -> time:
        return value


class RoutingRule(BaseModel):
    """First match wins (docs/sales/05-workflows.md § 5)."""

    model_config = ConfigDict(extra="ignore")

    #: Any of these matching sends the conversation to `team_id`. An empty list matches nothing.
    languages: list[str] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)
    #: True to match only conversations that started from a Click-to-WhatsApp ad.
    from_ad: bool | None = None
    team_id: UUID


class SalesSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    #: Minutes a waiting customer should wait, in business hours.
    first_response_target_min: int = Field(default=5, ge=1, le=24 * 60)
    #: Whether a salesperson sees their teams' unassigned queue. Read by RLS too
    #: (app.pool_visible, migration 0006), so the name here must not drift.
    unassigned_visible_to_sales: bool = True
    default_team_id: UUID | None = None
    #: A day missing from the map is a closed day. An empty map means always open.
    business_hours: dict[Weekday, OpenHours] = Field(default_factory=dict)
    routing_rules: list[RoutingRule] = Field(default_factory=list)
```

- [ ] **Step 4: Write the arithmetic**

```python
# apps/api/src/dealerai/sales/hours.py
"""Business-hours arithmetic for response targets.

A customer who writes at 23:30 is not late at 23:35. Targets count minutes the
team is actually open, in the tenant's own timezone — which is why this takes a
`tz` rather than reading one from the process.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from .settings import WEEKDAYS, SalesSettings

#: How far ahead to look for an open minute before giving up. A tenant whose
#: hours are all closed still gets a due time rather than none at all.
_HORIZON_DAYS = 14


def _hours_for(moment: datetime, settings: SalesSettings) -> tuple[time, time] | None:
    day = settings.business_hours.get(WEEKDAYS[moment.weekday()])
    return (day.open, day.close) if day else None


def is_open(moment: datetime, *, settings: SalesSettings, tz: ZoneInfo) -> bool:
    """Is the team open at this instant? A tenant with no hours is always open."""
    if not settings.business_hours:
        return True
    local = moment.astimezone(tz)
    hours = _hours_for(local, settings)
    return hours is not None and hours[0] <= local.time() < hours[1]


def due_at(
    waiting_since: datetime,
    *,
    settings: SalesSettings,
    tz: ZoneInfo,
    target_minutes: int | None = None,
) -> datetime:
    """When a reply to a message received at `waiting_since` becomes late."""
    remaining = timedelta(minutes=target_minutes or settings.first_response_target_min)
    if not settings.business_hours:
        return waiting_since + remaining

    cursor = waiting_since.astimezone(tz)
    for _ in range(_HORIZON_DAYS):
        hours = _hours_for(cursor, settings)
        if hours is None:  # a closed day: start at the next one
            cursor = (cursor + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            continue
        opens, closes = (cursor.replace(hour=h.hour, minute=h.minute, second=0, microsecond=0)
                         for h in hours)
        if cursor < opens:
            cursor = opens
        if cursor >= closes:  # after closing: try tomorrow
            cursor = (cursor + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            continue
        left_today = closes - cursor
        if remaining <= left_today:
            return (cursor + remaining).astimezone(waiting_since.tzinfo)
        remaining -= left_today
        cursor = (closes + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

    # Hours that never open: fall back to the clock rather than returning nothing.
    return waiting_since + remaining
```

- [ ] **Step 5: Add the timezone database**

In `apps/api/pyproject.toml`, under `dependencies`:

```toml
    # zoneinfo has no IANA database on Windows; this is data, not code.
    "tzdata>=2026.1",
```

Run: `cd apps/api && uv sync --all-extras --dev`

- [ ] **Step 6: Run the tests**

Run: `cd apps/api && uv run pytest tests/test_sales_hours.py -v && uv run mypy src`
Expected: PASS. If `test_minutes_left_at_closing_continue_the_next_morning` is off by a minute,
the bug is in the `left_today` comparison, not the test.

- [ ] **Step 7: Commit**

```bash
git add apps/api/src/dealerai/sales/settings.py apps/api/src/dealerai/sales/hours.py apps/api/tests/test_sales_hours.py apps/api/pyproject.toml apps/api/uv.lock
git commit -m "feat(sales): response targets in the tenant's business hours"
```

---

## Task 3: Who gets the conversation

**Files:**
- Create: `apps/api/src/dealerai/sales/assignment.py`
- Create: `apps/api/src/dealerai/events/handlers/inbox.py`
- Modify: `apps/api/src/dealerai/events/handlers/{__init__,parked}.py`
- Create: `apps/api/tests/test_assignment.py`

The choice is a pure function over candidates; the handler is the part that talks to the database.
Two conversations arriving at once must not both land on the same person, which is what
`for update skip locked` on the membership rows buys.

An unassigned conversation is not an error: nobody available means it stays in the team's queue and
the sweep in Task 5 tries again when the team opens.

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/test_assignment.py
"""Routing a waiting customer to a person, and never to two people at once."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import asyncpg

from conftest import MANAGER, SALES_1, SALES_2, TEAM_LOCAL, TENANT_A, reseed_with_people
from dealerai.events.bus import Event
from dealerai.events.handlers import inbox
from dealerai.sales.assignment import Candidate, choose

NOW = datetime(2026, 9, 17, 10, 0, tzinfo=UTC)


def _candidate(user_id: uuid.UUID, **overrides: object) -> Candidate:
    base: dict[str, object] = {
        "user_id": user_id,
        "languages": ("ar", "en"),
        "accepting_chats": True,
        "open_conversations": 0,
        "max_open_conversations": None,
        "last_assigned_at": None,
    }
    base.update(overrides)
    return Candidate(**base)  # type: ignore[arg-type]


def test_the_least_recently_assigned_person_takes_it() -> None:
    busy = _candidate(SALES_1, last_assigned_at=NOW)
    free = _candidate(SALES_2, last_assigned_at=NOW - timedelta(hours=2))
    assert choose([busy, free], language=None) == SALES_2


def test_someone_who_has_never_been_assigned_goes_first() -> None:
    assert choose([_candidate(SALES_1, last_assigned_at=NOW), _candidate(SALES_2)], language=None) == SALES_2


def test_a_shared_language_wins_over_the_rotation() -> None:
    """A French customer reaching an Arabic-only rep is a worse start than waiting
    one place longer in the queue."""
    arabic_only = _candidate(SALES_1, languages=("ar",))
    french = _candidate(SALES_2, languages=("fr", "en"), last_assigned_at=NOW)
    assert choose([arabic_only, french], language="fr") == SALES_2


def test_nobody_available_is_an_answer() -> None:
    away = _candidate(SALES_1, accepting_chats=False)
    full = _candidate(SALES_2, open_conversations=8, max_open_conversations=8)
    assert choose([away, full], language=None) is None


async def test_the_handler_assigns_and_says_so(db: None, su: asyncpg.Connection) -> None:
    conversation_id = await _waiting_conversation(su)

    await inbox.on_assign_requested(_event(conversation_id))

    row = await su.fetchrow(
        "select assigned_to, owner_id from conversations where id = $1", conversation_id
    )
    assert row is not None and row["assigned_to"] in (SALES_1, SALES_2)
    assert row["owner_id"] == row["assigned_to"], "the customer's owner follows the assignment"
    event_line = await su.fetchval(
        "select event from messages where conversation_id = $1 and kind = 'event'", conversation_id
    )
    assert event_line is not None
    assert await su.fetchval(
        "select count(*) from notifications where kind = 'assigned' and user_id = $1",
        row["assigned_to"],
    ) == 1


async def test_two_conversations_do_not_land_on_one_person(
    db: None, su: asyncpg.Connection
) -> None:
    """Both reps are free; the rotation must hand out one each."""
    first = await _waiting_conversation(su)
    second = await _waiting_conversation(su)

    await asyncio.gather(
        inbox.on_assign_requested(_event(first)),
        inbox.on_assign_requested(_event(second)),
    )

    assigned = [
        row["assigned_to"]
        for row in await su.fetch(
            "select assigned_to from conversations where id = any($1::uuid[])", [first, second]
        )
    ]
    assert None not in assigned
    assert len(set(assigned)) == 2, f"both went to the same person: {assigned}"


async def test_a_customer_who_already_has_a_rep_stays_with_them(
    db: None, su: asyncpg.Connection
) -> None:
    conversation_id = await _waiting_conversation(su, owner=SALES_2)
    await inbox.on_assign_requested(_event(conversation_id))
    assert (
        await su.fetchval("select assigned_to from conversations where id = $1", conversation_id)
        == SALES_2
    )
```

`_waiting_conversation` and `_event` are the fixtures this file needs; write them at the top of the
file: `reseed_with_people()` first, then a contact (optionally owned), a WhatsApp channel, and a
conversation with `team_id = TEAM_LOCAL`, `waiting_since = now()` and no assignee, plus an
`Event(event_type="conversation.assign_requested", payload={"conversation_id": str(id)})`.
Put both members of the Local team in `memberships` with `accepting_chats = true` — `reseed_with_people`
already does.

- [ ] **Step 2: Run it to verify it fails**

Run: `cd apps/api && uv run pytest tests/test_assignment.py -v`
Expected: FAIL — `No module named 'dealerai.sales.assignment'`.

- [ ] **Step 3: Write the choice**

```python
# apps/api/src/dealerai/sales/assignment.py
"""Who takes a waiting conversation. Pure: candidates in, one id out.

The database part (locking the rows so two arrivals cannot pick the same person)
lives in the handler; the rule itself is here, where it can be read.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from .settings import RoutingRule


@dataclass(frozen=True, slots=True)
class Candidate:
    user_id: UUID
    languages: tuple[str, ...]
    accepting_chats: bool
    open_conversations: int
    max_open_conversations: int | None
    last_assigned_at: datetime | None


def _available(candidate: Candidate) -> bool:
    if not candidate.accepting_chats:
        return False
    limit = candidate.max_open_conversations
    return limit is None or candidate.open_conversations < limit


def choose(candidates: Iterable[Candidate], *, language: str | None) -> UUID | None:
    """The least recently assigned available person, preferring a shared language.

    Language first, then rotation: a French customer reaching an Arabic-only rep
    is a worse start than waiting one place longer in the queue. Nobody available
    returns None — the conversation stays in the team's queue for the sweep.
    """
    available = [c for c in candidates if _available(c)]
    if not available:
        return None
    speaks = [c for c in available if language and language in c.languages]
    pool = speaks or available
    # Never assigned sorts first: a new rep should not wait for a full rotation.
    epoch = datetime.min.replace(tzinfo=UTC)
    return min(pool, key=lambda c: c.last_assigned_at or epoch).user_id


def route_to_team(
    rules: Sequence[RoutingRule],
    *,
    language: str | None,
    country: str | None,
    from_ad: bool,
    default_team_id: UUID | None,
) -> UUID | None:
    """First rule that matches, else the tenant's default team."""
    for rule in rules:
        if rule.languages and language not in rule.languages:
            continue
        if rule.countries and country not in rule.countries:
            continue
        if rule.from_ad is not None and rule.from_ad is not from_ad:
            continue
        return rule.team_id
    return default_team_id
```

- [ ] **Step 4: Write the handler**

```python
# apps/api/src/dealerai/events/handlers/inbox.py
"""Inbox handlers: assignment, notifications and the response-target sweep."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog

from ...db.session import tenant_session
from ...sales.assignment import Candidate, choose, route_to_team
from ...sales.settings import SalesSettings
from ..bus import Event, emit, handler

log = structlog.get_logger()

#: Locked so two arrivals cannot pick the same person; skipped rather than
#: queued so a second assignment happening right now picks the next one instead
#: of waiting for the first to commit.
_CANDIDATES = """
select m.user_id, m.languages, m.accepting_chats, m.max_open_conversations, m.last_assigned_at,
       (select count(*) from conversations c
         where c.assigned_to = m.user_id and c.status = 'open')        as open_conversations
from memberships m
join team_members tm on tm.user_id = m.user_id and tm.tenant_id = m.tenant_id
where m.tenant_id = $1 and tm.team_id = $2 and m.role in ('sales', 'manager')
for update of m skip locked
"""

_ASSIGN = """
update conversations set assigned_to = $2, owner_id = coalesce(owner_id, $2)
where id = $1 and assigned_to is null
returning contact_id, owner_id
"""


@handler("conversation.assign_requested")
async def on_assign_requested(event: Event) -> None:
    """Give a waiting conversation to someone, or leave it for the sweep."""
    if event.tenant_id is None:
        raise ValueError("conversation.assign_requested requires a tenant")
    conversation_id = UUID(str(event.payload["conversation_id"]))

    async with tenant_session(event.tenant_id) as conn, conn.transaction():
        row = await conn.fetchrow(
            """select cv.id, cv.assigned_to, cv.team_id,
                      ct.id as contact_id, ct.owner_id as contact_owner, ct.locale, ct.country,
                      t.sales_settings,
                      -- came from a Click-to-WhatsApp ad: the referral is on the
                      -- message that started the conversation (migration 0007)
                      exists (select 1 from messages m
                               where m.conversation_id = cv.id and m.referral is not null) as from_ad
               from conversations cv
               join contacts ct on ct.id = cv.contact_id
               join tenants t on t.id = cv.tenant_id
               where cv.id = $1""",
            conversation_id,
        )
        if row is None or row["assigned_to"] is not None:
            return

        settings = SalesSettings.model_validate(row["sales_settings"] or {})
        # The customer's own salesperson keeps them, if they are taking chats.
        chosen: UUID | None = None
        if row["contact_owner"] is not None:
            chosen = await conn.fetchval(
                """select user_id from memberships
                   where tenant_id = $1 and user_id = $2 and accepting_chats""",
                event.tenant_id,
                row["contact_owner"],
            )

        team_id = row["team_id"] or route_to_team(
            settings.routing_rules,
            language=row["locale"],
            country=row["country"],
            from_ad=row["from_ad"],
            default_team_id=settings.default_team_id,
        )
        if chosen is None and team_id is not None:
            candidates = [
                Candidate(
                    user_id=c["user_id"],
                    languages=tuple(c["languages"] or ()),
                    accepting_chats=c["accepting_chats"],
                    open_conversations=c["open_conversations"],
                    max_open_conversations=c["max_open_conversations"],
                    last_assigned_at=c["last_assigned_at"],
                )
                for c in await conn.fetch(_CANDIDATES, event.tenant_id, team_id)
            ]
            chosen = choose(candidates, language=row["locale"])

        if chosen is None:
            # Not a failure: the team is closed or full. The sweep tries again.
            log.info("assignment_deferred", conversation_id=str(conversation_id), team=str(team_id))
            if team_id is not None and row["team_id"] is None:
                await conn.execute(
                    "update conversations set team_id = $2 where id = $1", conversation_id, team_id
                )
            return

        assigned = await conn.fetchrow(_ASSIGN, conversation_id, chosen)
        if assigned is None:  # someone else took it between the read and the write
            return
        await conn.execute(
            "update memberships set last_assigned_at = now() where tenant_id = $1 and user_id = $2",
            event.tenant_id,
            chosen,
        )
        await conn.execute(
            "update contacts set owner_id = coalesce(owner_id, $2) where id = $1",
            assigned["contact_id"],
            chosen,
        )
        name = await conn.fetchval("select full_name from profiles where id = $1", chosen)
        await _event_line(conn, event.tenant_id, conversation_id, "assigned", f"Assigned to {name}")
        await _notify(
            conn,
            tenant_id=event.tenant_id,
            user_id=chosen,
            kind="assigned",
            title="A customer is waiting for you",
            entity={"type": "conversation", "id": str(conversation_id)},
            dedupe_key=f"assigned:{conversation_id}:{chosen}",
        )


async def _event_line(
    conn: Any, tenant_id: UUID, conversation_id: UUID, kind: str, text: str
) -> None:
    """A grey line in the thread. The history of a conversation is in the thread,
    not in a separate audit nobody opens."""
    await conn.execute(
        """insert into messages (tenant_id, conversation_id, kind, type, direction, sender,
                                 origin, event)
           values ($1, $2, 'event', 'text', 'out', 'system', 'system', $3)""",
        tenant_id,
        conversation_id,
        {"type": kind, "text": text},
    )


async def _notify(
    conn: Any,
    *,
    tenant_id: UUID,
    user_id: UUID,
    kind: str,
    title: str,
    body: str | None = None,
    entity: dict[str, str] | None = None,
    dedupe_key: str | None = None,
) -> None:
    await conn.execute(
        """insert into notifications (tenant_id, user_id, kind, title, body, href, entity,
                                      dedupe_key)
           values ($1, $2, $3, $4, $5, $6, $7, $8)
           on conflict do nothing""",
        tenant_id,
        user_id,
        kind,
        title,
        body,
        f"/inbox/{entity['id']}" if entity and entity.get("type") == "conversation" else None,
        entity or {},
        dedupe_key,
    )
```

- [ ] **Step 5: Register the handler and unpark the type**

In `events/handlers/__init__.py`, add `inbox` to the imports and `__all__`. In
`events/handlers/parked.py`, delete the `conversation.assign_requested` entry — `bus.register`
raises if both exist, which is the point.

- [ ] **Step 6: Run the tests**

Run: `cd apps/api && uv run pytest tests/test_assignment.py tests/test_import_contracts.py -v`
Expected: PASS, including the contract test that every emitted type has exactly one handler.

- [ ] **Step 7: Commit**

```bash
git add apps/api/src/dealerai/sales/assignment.py apps/api/src/dealerai/events/handlers apps/api/tests/test_assignment.py
git commit -m "feat(sales): route a waiting conversation to a salesperson"
```

---

## Task 4: Telling the right person

**Files:**
- Modify: `apps/api/src/dealerai/events/handlers/inbox.py`
- Modify: `apps/api/src/dealerai/events/handlers/parked.py`
- Create: `apps/api/src/dealerai/routes/notifications.py`
- Modify: `apps/api/src/dealerai/main.py`
- Create: `apps/api/tests/test_notifications.py`

S1 already emits `notification.requested` from five places — a customer message, a rejected template,
a disconnected channel, a quality warning, an assignment. This gives them a recipient and a row.

Who hears about a customer message: the assignee. If nobody is assigned yet, the team's managers,
because an unanswered customer is a manager's problem before it is anyone's fault.

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/test_notifications.py
"""Notifications reach one person, once, and only they can read them."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator

import asyncpg
import pytest
from fastapi.testclient import TestClient

from conftest import MANAGER, SALES_1, TEAM_LOCAL, TENANT_A, reseed_with_people
from dealerai.config import get_settings
from dealerai.core.security import mint_test_token
from dealerai.events.bus import Event
from dealerai.events.handlers import inbox
from dealerai.main import app

SECRET = "super-secret-jwt-token-with-at-least-32-characters-long"


def _event(payload: dict[str, object]) -> Event:
    return Event(
        id=1,
        tenant_id=TENANT_A,
        event_type="notification.requested",
        payload=payload,
        attempts=1,
        dedupe_key=None,
    )


async def test_the_assignee_hears_about_their_customer(
    db: None, su: asyncpg.Connection
) -> None:
    conversation_id = await _conversation(su, assigned_to=SALES_1)
    message_id = await _message(su, conversation_id)

    await inbox.on_notification_requested(
        _event({"conversation_id": str(conversation_id), "message_id": str(message_id)})
    )

    rows = await su.fetch("select user_id, kind, href from notifications")
    assert [(r["user_id"], r["kind"]) for r in rows] == [(SALES_1, "message_received")]
    assert rows[0]["href"] == f"/inbox/{conversation_id}"


async def test_an_unassigned_customer_is_the_managers_problem(
    db: None, su: asyncpg.Connection
) -> None:
    conversation_id = await _conversation(su, assigned_to=None, team_id=TEAM_LOCAL)
    message_id = await _message(su, conversation_id)

    await inbox.on_notification_requested(
        _event({"conversation_id": str(conversation_id), "message_id": str(message_id)})
    )

    recipients = [r["user_id"] for r in await su.fetch("select user_id from notifications")]
    assert recipients == [MANAGER]


async def test_the_same_message_notifies_once(db: None, su: asyncpg.Connection) -> None:
    conversation_id = await _conversation(su, assigned_to=SALES_1)
    message_id = await _message(su, conversation_id)
    event = _event({"conversation_id": str(conversation_id), "message_id": str(message_id)})

    await inbox.on_notification_requested(event)
    await inbox.on_notification_requested(event)

    assert await su.fetchval("select count(*) from notifications") == 1


async def test_a_rejected_template_reaches_the_people_who_can_fix_it(
    db: None, su: asyncpg.Connection
) -> None:
    channel_id = await _channel(su)
    await inbox.on_notification_requested(
        _event({"kind": "template_rejected", "channel_id": str(channel_id),
                "template_id": str(uuid.uuid4())})
    )
    roles = await su.fetch(
        """select m.role from notifications n
           join memberships m on m.user_id = n.user_id and m.tenant_id = n.tenant_id"""
    )
    assert {r["role"] for r in roles} == {"owner"}, "only owners and admins can act on this"


def test_a_person_reads_only_their_own(client: TestClient) -> None:
    mine = client.get("/v1/notifications", headers=_auth(SALES_1))
    assert mine.status_code == 200
    assert all(n["kind"] for n in mine.json()["data"])
    assert client.get("/v1/notifications", headers=_auth(MANAGER)).json()["data"] == []


def test_marking_read_is_idempotent(client: TestClient) -> None:
    ids = [n["id"] for n in client.get("/v1/notifications", headers=_auth(SALES_1)).json()["data"]]
    for _ in range(2):
        assert client.post(
            "/v1/notifications/read", json={"ids": ids}, headers=_auth(SALES_1)
        ).status_code == 204
    unread = client.get(
        "/v1/notifications?unread_only=true", headers=_auth(SALES_1)
    ).json()["data"]
    assert unread == []
```

Write the `_conversation`, `_message`, `_channel`, `_auth` and `client` helpers at the top, following
`tests/test_whatsapp_routes_access.py`: `reseed_with_people()`, a WhatsApp channel, a contact, then a
conversation. The `client` fixture seeds one unread notification for `SALES_1` before yielding.

- [ ] **Step 2: Run it to verify it fails**

Run: `cd apps/api && uv run pytest tests/test_notifications.py -v`
Expected: FAIL — `module 'dealerai.events.handlers.inbox' has no attribute 'on_notification_requested'`.

- [ ] **Step 3: Write the handler**

Add to `events/handlers/inbox.py`:

```python
#: kind -> (title, what the body says). The text lives here rather than in the
#: emitters, so a notification reads the same wherever it was raised.
_NOTIFICATIONS = {
    "message_received": ("New message", None),
    "assigned": ("A customer is waiting for you", None),
    "waiting_due_soon": ("A customer is about to wait too long", None),
    "waiting_missed": ("A customer has been waiting too long", None),
    "unassigned_waiting": ("An unassigned customer is waiting", None),
    "template_rejected": ("WhatsApp rejected a template", "Open Settings → Channels to fix it."),
    "channel_disconnected": ("WhatsApp was disconnected", "Reconnect it in Settings → Channels."),
    "channel_quality": ("WhatsApp flagged the number's quality", None),
}

_ADMINS = """
select user_id from memberships where tenant_id = $1 and role in ('owner', 'admin')
"""

_TEAM_MANAGERS = """
select m.user_id from memberships m
join team_members tm on tm.user_id = m.user_id and tm.tenant_id = m.tenant_id
where m.tenant_id = $1 and tm.team_id = $2 and m.role = 'manager'
"""


@handler("notification.requested")
async def on_notification_requested(event: Event) -> None:
    """Turn an intent to notify into rows for the people who should act."""
    if event.tenant_id is None:
        raise ValueError("notification.requested requires a tenant")
    payload = event.payload
    kind = str(payload.get("kind") or "message_received")
    if kind not in _NOTIFICATIONS:
        log.warning("notification_kind_unknown", kind=kind)
        return
    title, body = _NOTIFICATIONS[kind]

    async with tenant_session(event.tenant_id) as conn, conn.transaction():
        if kind == "message_received":
            conversation_id = UUID(str(payload["conversation_id"]))
            row = await conn.fetchrow(
                """select cv.assigned_to, cv.team_id, ct.full_name
                   from conversations cv join contacts ct on ct.id = cv.contact_id
                   where cv.id = $1""",
                conversation_id,
            )
            if row is None:
                return
            recipients = (
                [row["assigned_to"]]
                if row["assigned_to"]
                # Nobody owns it yet, so it is the managers' problem, not nobody's.
                else [r["user_id"] for r in await conn.fetch(
                    _TEAM_MANAGERS, event.tenant_id, row["team_id"])]
            )
            entity = {"type": "conversation", "id": str(conversation_id)}
            title = f"{row['full_name'] or 'A customer'} sent a message"
            dedupe = f"message:{payload.get('message_id')}"
        else:
            recipients = [r["user_id"] for r in await conn.fetch(_ADMINS, event.tenant_id)]
            entity = {k: str(v) for k, v in payload.items() if k != "kind"}
            dedupe = f"{kind}:{payload.get('template_id') or payload.get('channel_id')}"

        for user_id in recipients:
            await _notify(
                conn,
                tenant_id=event.tenant_id,
                user_id=user_id,
                kind=kind,
                title=title,
                body=body,
                entity=entity,
                dedupe_key=f"{dedupe}:{user_id}",
            )
```

Remove `notification.requested` from `parked.py`.

- [ ] **Step 4: Write the routes**

```python
# apps/api/src/dealerai/routes/notifications.py
"""A person's own notifications. RLS makes "own" true; nothing here filters by user."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, Field, model_validator

from ..db.session import tenant_session
from ..deps import Ctx

router = APIRouter(prefix="/v1/notifications", tags=["notifications"])


class NotificationOut(BaseModel):
    id: UUID
    kind: str
    title: str
    body: str | None
    href: str | None
    entity: dict[str, Any]
    read_at: datetime | None
    created_at: datetime


class NotificationPage(BaseModel):
    data: list[NotificationOut]
    next_cursor: str | None = None
    unread: int


class ReadIn(BaseModel):
    ids: list[UUID] = Field(default_factory=list)
    all: bool = False

    @model_validator(mode="after")
    def one_or_the_other(self) -> ReadIn:
        if bool(self.ids) == self.all:
            raise ValueError("provide either ids or all")
        return self


@router.get("", response_model=NotificationPage)
async def list_notifications(ctx: Ctx, unread_only: bool = False, limit: int = 50) -> dict[str, Any]:
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        rows = await conn.fetch(
            """select id, kind, title, body, href, entity, read_at, created_at
               from notifications
               where ($1::boolean is not true or read_at is null)
               order by created_at desc limit $2""",
            unread_only,
            min(limit, 100),
        )
        unread = await conn.fetchval("select count(*) from notifications where read_at is null")
    return {"data": [dict(row) for row in rows], "next_cursor": None, "unread": unread}


@router.post("/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_read(ctx: Ctx, body: ReadIn) -> Response:
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        await conn.execute(
            """update notifications set read_at = now()
               where read_at is null and ($2::boolean or id = any($1::uuid[]))""",
            body.ids,
            body.all,
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

Mount it in `main.py` beside the others.

- [ ] **Step 5: Run the tests**

Run: `cd apps/api && uv run pytest tests/test_notifications.py tests/test_import_contracts.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/api/src/dealerai apps/api/tests/test_notifications.py
git commit -m "feat(sales): notifications reach the person who can act"
```

---

## Task 5: The waiting timer

**Files:**
- Modify: `apps/api/src/dealerai/events/handlers/whatsapp.py` (`sla_due_at` in business hours)
- Modify: `apps/api/src/dealerai/events/handlers/inbox.py` (the check, and re-trying assignment)
- Modify: `apps/api/src/dealerai/events/handlers/parked.py`
- Create: `apps/api/tests/test_response_targets.py`

S1 set `sla_due_at` to "message time plus five minutes", ignoring business hours — fine while nothing
read it, wrong the moment a manager does. Task 2 built the arithmetic; this wires it in.

> `ponytail:` no periodic sweep and no scheduler. A conversation that starts waiting schedules its
> own two checks — due soon, then missed — on the existing queue, which is exact rather than
> approximate and costs one row instead of a job every minute per tenant. The screen never depends
> on them: `sla_state` is computed from `sla_due_at` when the inbox is read, so a lost event costs a
> notification, not a wrong timer. **Upgrade trigger:** a second thing needs a real clock (the daily
> brief in S6, score decay), and then APScheduler earns its place emitting both.

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/test_response_targets.py
"""A waiting customer has a due time in business hours, and it stops when we reply."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import asyncpg

from conftest import MANAGER, SALES_1, TENANT_A
from dealerai.events.bus import Event
from dealerai.events.handlers import inbox


async def test_a_waiting_conversation_schedules_its_own_checks(
    db: None, su: asyncpg.Connection
) -> None:
    """The first inbound message is what starts the timer (handler in S1)."""
    conversation_id = await _waiting_conversation(su, assigned_to=SALES_1)
    [check] = await su.fetch(
        "select run_after, dedupe_key from events where event_type = 'conversation.sla_check'"
    )
    due_at = await su.fetchval(
        "select sla_due_at from conversations where id = $1", conversation_id
    )
    assert check["run_after"] < due_at, "the first check runs before the target, not after"


async def test_due_soon_then_missed_notifies_once_each(
    db: None, su: asyncpg.Connection
) -> None:
    conversation_id = await _waiting_conversation(su, assigned_to=SALES_1, overdue=True)

    await inbox.on_sla_check(_check(conversation_id, level="due_soon"))
    await inbox.on_sla_check(_check(conversation_id, level="due_soon"))
    await inbox.on_sla_check(_check(conversation_id, level="missed"))

    kinds = [
        row["kind"]
        for row in await su.fetch("select kind from notifications order by created_at")
    ]
    assert kinds == ["waiting_due_soon", "waiting_missed"]


async def test_a_missed_target_also_reaches_the_manager(
    db: None, su: asyncpg.Connection
) -> None:
    conversation_id = await _waiting_conversation(su, assigned_to=SALES_1, overdue=True)
    await inbox.on_sla_check(_check(conversation_id, level="missed"))
    recipients = {
        row["user_id"] for row in await su.fetch("select user_id from notifications")
    }
    assert recipients == {SALES_1, MANAGER}


async def test_a_reply_stops_the_timer(db: None, su: asyncpg.Connection) -> None:
    """The salesperson answered: the check that fires later must do nothing."""
    conversation_id = await _waiting_conversation(su, assigned_to=SALES_1, overdue=True)
    await su.execute(
        """update conversations set waiting_since = null, sla_due_at = null,
                                    first_response_at = now() where id = $1""",
        conversation_id,
    )

    await inbox.on_sla_check(_check(conversation_id, level="missed"))

    assert await su.fetchval("select count(*) from notifications") == 0


async def test_an_unassigned_conversation_is_tried_again_when_the_team_opens(
    db: None, su: asyncpg.Connection
) -> None:
    conversation_id = await _waiting_conversation(su, assigned_to=None, nobody_available=True)
    await inbox.on_assign_requested(
        Event(
            id=2,
            tenant_id=TENANT_A,
            event_type="conversation.assign_requested",
            payload={"conversation_id": str(conversation_id)},
            attempts=1,
            dedupe_key=None,
        )
    )
    retry = await su.fetchrow(
        """select run_after from events
           where event_type = 'conversation.assign_requested' and status = 'pending'"""
    )
    assert retry is not None and retry["run_after"] > datetime.now(UTC)
```

- [ ] **Step 2: Compute the due time where the timer starts**

In `events/handlers/whatsapp.py`, `on_message_received`, replace the naive `sla_due_at` arithmetic:

```python
        settings = SalesSettings.model_validate(
            await conn.fetchval("select sales_settings from tenants where id=$1", tenant_id) or {}
        )
        tenant_tz = ZoneInfo(
            await conn.fetchval("select timezone from tenants where id=$1", tenant_id) or "UTC"
        )
        started_waiting = await conn.fetchval(_WAITING, conversation_id, sent_at)  # returns waiting_since
        due = hours.due_at(started_waiting, settings=settings, tz=tenant_tz)
        await conn.execute(
            "update conversations set sla_due_at = $2 where id = $1 and waiting_since = $3",
            conversation_id,
            due,
            started_waiting,
        )
        await emit(
            conn,
            "conversation.sla_check",
            {"conversation_id": str(conversation_id), "level": "due_soon",
             "waiting_since": started_waiting.isoformat()},
            tenant_id=tenant_id,
            dedupe_key=f"sla:{conversation_id}:{started_waiting.isoformat()}:due_soon",
            run_after=due - timedelta(minutes=2),
            priority=8,
        )
```

`_WAITING` gains `returning waiting_since` so the due time is computed against the moment the customer
actually started waiting, not against this message.

- [ ] **Step 3: Write the check**

Add to `events/handlers/inbox.py`:

```python
@handler("conversation.sla_check")
async def on_sla_check(event: Event) -> None:
    """Warn before the target, then once after it. Silent if the customer was answered."""
    if event.tenant_id is None:
        raise ValueError("conversation.sla_check requires a tenant")
    conversation_id = UUID(str(event.payload["conversation_id"]))
    level = str(event.payload.get("level") or "due_soon")
    waiting_since = str(event.payload.get("waiting_since") or "")

    async with tenant_session(event.tenant_id) as conn, conn.transaction():
        row = await conn.fetchrow(
            """select cv.waiting_since, cv.sla_due_at, cv.assigned_to, cv.team_id,
                      ct.full_name
               from conversations cv join contacts ct on ct.id = cv.contact_id
               where cv.id = $1""",
            conversation_id,
        )
        # Answered, or this check belongs to an older waiting period: nothing to say.
        if row is None or row["waiting_since"] is None:
            return
        if waiting_since and row["waiting_since"].isoformat() != waiting_since:
            return

        kind = "waiting_due_soon" if level == "due_soon" else "waiting_missed"
        who = row["full_name"] or "A customer"
        recipients = [row["assigned_to"]] if row["assigned_to"] else []
        if level == "missed":
            recipients += [
                r["user_id"]
                for r in await conn.fetch(_TEAM_MANAGERS, event.tenant_id, row["team_id"])
            ]
        if not recipients:
            recipients = [
                r["user_id"]
                for r in await conn.fetch(_TEAM_MANAGERS, event.tenant_id, row["team_id"])
            ]
            kind = "unassigned_waiting"

        for user_id in dict.fromkeys(recipients):  # ordered, deduplicated
            await _notify(
                conn,
                tenant_id=event.tenant_id,
                user_id=user_id,
                kind=kind,
                title=f"{who} is waiting",
                entity={"type": "conversation", "id": str(conversation_id)},
                dedupe_key=f"{kind}:{conversation_id}:{row['waiting_since'].isoformat()}:{user_id}",
            )

        if level == "due_soon":
            await emit(
                conn,
                "conversation.sla_check",
                {"conversation_id": str(conversation_id), "level": "missed",
                 "waiting_since": row["waiting_since"].isoformat()},
                tenant_id=event.tenant_id,
                dedupe_key=f"sla:{conversation_id}:{row['waiting_since'].isoformat()}:missed",
                run_after=row["sla_due_at"],
                priority=8,
            )
```

- [ ] **Step 4: Try assignment again when nobody was available**

In `on_assign_requested`, where it currently logs `assignment_deferred`, schedule the retry before
returning:

```python
            await emit(
                conn,
                "conversation.assign_requested",
                {"conversation_id": str(conversation_id)},
                tenant_id=event.tenant_id,
                dedupe_key=f"assign-retry:{conversation_id}:{int(datetime.now(UTC).timestamp()) // 900}",
                run_after=datetime.now(UTC) + timedelta(minutes=15),
                priority=8,
            )
```

Fifteen minutes, not "when the team opens": a rep coming back from lunch is as common as a team
opening, and a quarter-hour of queue time costs nothing.

- [ ] **Step 5: Unpark `conversation.sla_check`**

It was never parked (S1 did not emit it) — instead confirm `test_every_emitted_event_has_a_handler`
still passes, which it will once the handler is registered.

- [ ] **Step 6: Run the tests**

Run: `cd apps/api && uv run pytest tests/test_response_targets.py tests/test_whatsapp_ingest.py -v`
Expected: PASS. The S1 ingest test that asserted the naive `sla_due_at` needs updating to the
business-hours value — change the assertion, not the behaviour.

- [ ] **Step 7: Commit**

```bash
git add apps/api/src/dealerai apps/api/tests/test_response_targets.py apps/api/tests/test_whatsapp_ingest.py
git commit -m "feat(sales): response targets that count business hours"
```

---

## Task 6: The queue

**Files:**
- Create: `apps/api/src/dealerai/db/queries/inbox.py`
- Modify: `apps/api/src/dealerai/routes/inbox.py`
- Create: `apps/api/tests/test_inbox_list.py`

Four views, defined once on the server so the tabs cannot drift between clients, and one order:
customers waiting on us first, oldest first, then latest activity. Visibility is not in this query at
all — RLS already decided which conversations exist for this caller, which is why a rep asking for
`all` sees their own rows rather than an error.

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/test_inbox_list.py
"""The queue: what each role sees, in what order, and what the counts say."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest
from fastapi.testclient import TestClient

from conftest import MANAGER, OWNER, SALES_1, SALES_2, TEAM_LOCAL, TENANT_A
from dealerai.main import app

NOW = datetime.now(UTC)


def test_mine_holds_only_my_conversations(client: TestClient) -> None:
    rows = client.get("/v1/conversations?view=mine", headers=_auth(SALES_1)).json()["data"]
    assert {row["assignee"]["id"] for row in rows} == {str(SALES_1)}


def test_waiting_customers_come_first_oldest_first(client: TestClient) -> None:
    rows = client.get("/v1/conversations?view=all", headers=_auth(OWNER)).json()["data"]
    waiting = [row["waiting_since"] for row in rows if row["waiting_since"]]
    assert waiting == sorted(waiting), "the customer waiting longest is not at the top"
    assert all(row["waiting_since"] for row in rows[: len(waiting)])


def test_a_salesperson_asking_for_everything_still_sees_their_own(client: TestClient) -> None:
    """RLS answers the question the view cannot: `all` is not an escalation."""
    rows = client.get("/v1/conversations?view=all", headers=_auth(SALES_1)).json()["data"]
    assert rows, "a salesperson sees their own conversations"
    assert all(row["assignee"]["id"] == str(SALES_1) for row in rows if row["assignee"])


def test_the_team_view_needs_a_manager(client: TestClient) -> None:
    assert client.get("/v1/conversations?view=team", headers=_auth(SALES_1)).status_code == 403
    assert client.get("/v1/conversations?view=team", headers=_auth(MANAGER)).status_code == 200


def test_unread_counts_what_i_have_not_read(client: TestClient) -> None:
    [row] = [
        r
        for r in client.get("/v1/conversations?view=mine", headers=_auth(SALES_1)).json()["data"]
        if r["unread_count"] > 0
    ]
    client.post(f"/v1/conversations/{row['id']}/read", headers=_auth(SALES_1))
    after = client.get("/v1/conversations?view=mine", headers=_auth(SALES_1)).json()["data"]
    assert next(r for r in after if r["id"] == row["id"])["unread_count"] == 0


def test_the_timer_says_how_late_we_are(client: TestClient) -> None:
    rows = client.get("/v1/conversations?view=all", headers=_auth(OWNER)).json()["data"]
    states = {row["sla_state"] for row in rows}
    assert "breached" in states
    assert None in states, "a conversation nobody is waiting on has no state"


def test_search_finds_a_voice_note_by_what_was_said(client: TestClient) -> None:
    rows = client.get(
        "/v1/conversations?view=all&q=land%20cruiser", headers=_auth(OWNER)
    ).json()["data"]
    assert len(rows) == 1


def test_search_finds_a_customer_by_number(client: TestClient) -> None:
    rows = client.get("/v1/conversations?view=all&q=500000101", headers=_auth(OWNER)).json()["data"]
    assert len(rows) == 1


def test_counts_cover_every_view_the_caller_may_open(client: TestClient) -> None:
    counts = client.get("/v1/conversations/counts", headers=_auth(MANAGER)).json()
    assert set(counts) == {"mine", "unassigned", "team"}
    assert counts["unassigned"]["waiting"] >= 1


def test_the_page_walks_forward_without_repeating(client: TestClient) -> None:
    first = client.get("/v1/conversations?view=all&limit=2", headers=_auth(OWNER)).json()
    assert first["next_cursor"]
    second = client.get(
        f"/v1/conversations?view=all&limit=2&cursor={first['next_cursor']}", headers=_auth(OWNER)
    ).json()
    assert {row["id"] for row in first["data"]}.isdisjoint({row["id"] for row in second["data"]})
```

The `client` fixture seeds a small, deliberate workspace: one conversation assigned to `SALES_1`
waiting since 40 minutes ago with an overdue `sla_due_at` and two unread inbound messages; one
assigned to `SALES_2`; one unassigned in `TEAM_LOCAL` waiting 5 minutes; one closed with no waiting;
and one voice note whose transcript says "is the land cruiser still available". Build it with the
helpers from `tests/test_whatsapp_routes_access.py`.

- [ ] **Step 2: Run it to verify it fails**

Run: `cd apps/api && uv run pytest tests/test_inbox_list.py -v`
Expected: FAIL — 404, the route does not exist.

- [ ] **Step 3: Write the queries**

```python
# apps/api/src/dealerai/db/queries/inbox.py
"""The inbox's SQL, in one place.

Visibility is absent on purpose: the policies in 0006 already decided which rows
exist for this session, so a view here is a filter over what the caller can see,
never a claim about what they may see.
"""

from __future__ import annotations

from typing import Literal

View = Literal["mine", "unassigned", "team", "all"]

#: Which views a scope may open. `team` and `all` are the manager's and the
#: owner's; a salesperson asking for them gets 403, not an empty list, because
#: an empty list would look like "no work today".
VIEWS_BY_SCOPE: dict[str, tuple[View, ...]] = {
    "own": ("mine", "unassigned"),
    "team": ("mine", "unassigned", "team"),
    "all": ("mine", "unassigned", "team", "all"),
}

_VIEW_SQL: dict[View, str] = {
    "mine": "cv.assigned_to = $1",
    "unassigned": "cv.assigned_to is null",
    "team": "cv.team_id = any (coalesce((select app.my_team_ids()), '{}'))",
    "all": "true",
}

#: Waiting first, longest first, then the liveliest. Ties break on id so a page
#: boundary can never show the same row twice.
_ORDER = """
order by coalesce(cv.waiting_since, 'infinity'::timestamptz) asc,
         coalesce(cv.last_message_at, '-infinity'::timestamptz) desc,
         cv.id asc
"""

#: Mixed directions, so the keyset is written out rather than a row comparison.
#: The list is filtered to one channel only when the tenant has more than one
#: ([08](../08-screens.md) § 2); an empty string means every channel.
_CHANNEL = "and ($4 = '' or cv.channel_id = $4::uuid)"

_AFTER = """
and (coalesce(cv.waiting_since, 'infinity'::timestamptz) > $5
     or (coalesce(cv.waiting_since, 'infinity'::timestamptz) = $5
         and (coalesce(cv.last_message_at, '-infinity'::timestamptz) < $6
              or (coalesce(cv.last_message_at, '-infinity'::timestamptz) = $6 and cv.id > $7))))
"""

_SEARCH = """
and ($3 = ''
     or ct.full_name ilike '%' || $3 || '%'
     or exists (select 1 from contact_identities i
                 where i.contact_id = ct.id and i.value ilike '%' || $3 || '%')
     or exists (select 1 from messages m
                 where m.conversation_id = cv.id
                   and to_tsvector('simple', coalesce(m.body, '') || ' ' ||
                                   coalesce(m.transcript->>'text', ''))
                       @@ plainto_tsquery('simple', $3)))
"""

_SUMMARY = """
select cv.id, cv.status, cv.last_message_at, cv.waiting_since, cv.sla_due_at,
       cv.wa_window_expires_at, cv.assigned_to, cv.team_id,
       ct.id as contact_id, ct.full_name, ct.country, ct.locale, ct.tags, ct.last_seen_at,
       ct.owner_id as contact_owner_id,
       owner.full_name as contact_owner_name,
       ch.id as channel_id, ch.platform,
       coalesce(ch.display_name, ch.handle) as channel_name,
       team.name as team_name,
       assignee.full_name as assignee_name, assignee.avatar_url as assignee_avatar,
       last.body, last.type as last_type, last.direction, last.origin, last.transcript,
       last.created_at as last_at,
       (select count(*) from messages unread
         where unread.conversation_id = cv.id and unread.direction = 'in'
           and unread.kind = 'message'
           and unread.created_at > coalesce(reads.last_read_at, '-infinity'::timestamptz)
       ) as unread_count
from conversations cv
join contacts ct on ct.id = cv.contact_id
left join profiles owner on owner.id = ct.owner_id
left join channels ch on ch.id = cv.channel_id
left join teams team on team.id = cv.team_id
left join profiles assignee on assignee.id = cv.assigned_to
left join conversation_reads reads
       on reads.conversation_id = cv.id and reads.user_id = $1
left join lateral (
    select m.body, m.type, m.direction, m.origin, m.transcript, m.created_at
    from messages m
    where m.conversation_id = cv.id and m.kind = 'message'
    order by m.created_at desc limit 1
) last on true
where ($2 = '' or cv.status = $2)
"""


def list_sql(view: View, *, with_cursor: bool) -> str:
    """$1 user, $2 status, $3 search, $4 channel, [$5 $6 $7 cursor], $8 limit.

    No tenant parameter: the session already carries it and RLS applies it. A
    parameter the SQL does not read is a parameter that drifts.
    """
    # asyncpg refuses a parameter the query never mentions, so the limit takes
    # whichever number is next once the cursor is in or out.
    limit_param = 8 if with_cursor else 5
    return (
        f"{_SUMMARY} and {_VIEW_SQL[view]} {_SEARCH} {_CHANNEL}"
        f" {_AFTER if with_cursor else ''} {_ORDER} limit ${limit_param}"
    )


COUNTS = """
select count(*) filter (where cv.waiting_since is not null) as waiting,
       coalesce(sum((select count(*) from messages unread
                      where unread.conversation_id = cv.id and unread.direction = 'in'
                        and unread.kind = 'message'
                        and unread.created_at > coalesce(reads.last_read_at,
                                                        '-infinity'::timestamptz))), 0) as unread
from conversations cv
left join conversation_reads reads on reads.conversation_id = cv.id and reads.user_id = $1
where cv.status = 'open' and {view}
"""
```

- [ ] **Step 4: Write the route**

Add to `routes/inbox.py` (which already holds the send route):

```python
class UserRef(BaseModel):
    id: UUID
    name: str | None
    avatar_url: str | None = None


class ContactSummary(BaseModel):
    id: UUID
    name: str | None
    country: str | None
    language: str | None
    tags: list[str]
    owner: UserRef | None
    last_seen_at: datetime | None


class LastMessage(BaseModel):
    preview: str
    type: str
    direction: Literal["in", "out"]
    origin: str
    at: datetime


class ConversationSummary(BaseModel):
    id: UUID
    channel: dict[str, Any] | None
    contact: ContactSummary
    status: str
    assignee: UserRef | None
    team: dict[str, Any] | None
    last_message: LastMessage | None
    unread_count: int
    waiting_since: datetime | None
    sla_due_at: datetime | None
    sla_state: Literal["ok", "due_soon", "breached"] | None
    window_expires_at: datetime | None
    #: Always false in S2; the copilot arrives in S4 and this is what the row reads.
    has_ai_draft: bool = False


class ConversationPage(BaseModel):
    data: list[ConversationSummary]
    next_cursor: str | None


#: How close to the target counts as "about to be late" — the same two minutes
#: the due-soon notification uses, so the amber row and the ping agree.
DUE_SOON = timedelta(minutes=2)


def _sla_state(waiting_since: datetime | None, due_at: datetime | None, now: datetime) -> str | None:
    if waiting_since is None or due_at is None:
        return None
    if now >= due_at:
        return "breached"
    return "due_soon" if due_at - now <= DUE_SOON else "ok"


def _preview(row: Mapping[str, Any]) -> str:
    """What the row shows: the text, or what kind of thing arrived."""
    if row["body"]:
        return str(row["body"])[:160]
    transcript = (row["transcript"] or {}).get("text") if row["transcript"] else None
    if transcript:
        return str(transcript)[:160]
    return {"image": "Photo", "audio": "Voice note", "video": "Video", "document": "Document",
            "location": "Location", "sticker": "Sticker", "template": "Template"}.get(
        str(row["last_type"]), "Message"
    )


#: A cursor is this server's business: three sort keys, base64'd so nobody is
#: tempted to build one by hand.
_FOREVER = datetime.max.replace(tzinfo=UTC)
_NEVER = datetime.min.replace(tzinfo=UTC)


def encode_cursor(row: Mapping[str, Any]) -> str:
    waiting = row["waiting_since"] or _FOREVER
    last = row["last_message_at"] or _NEVER
    return base64.urlsafe_b64encode(
        f"{waiting.isoformat()}|{last.isoformat()}|{row['id']}".encode()
    ).decode()


def decode_cursor(cursor: str) -> tuple[datetime, datetime, UUID]:
    try:
        waiting, last, conversation_id = base64.urlsafe_b64decode(cursor).decode().split("|")
        return datetime.fromisoformat(waiting), datetime.fromisoformat(last), UUID(conversation_id)
    except (ValueError, binascii.Error) as exc:
        raise Unusable("that cursor is not one of ours") from exc


@router.get("", response_model=ConversationPage)
async def list_conversations(
    ctx: Ctx,
    view: View = "mine",
    status_filter: Annotated[str, Query(alias="status")] = "open",
    q: str = "",
    channel_id: str = "",
    cursor: str | None = None,
    limit: int = 30,
) -> dict[str, Any]:
    if view not in VIEWS_BY_SCOPE[ctx.scope]:
        # 403, not an empty list: an empty list reads as "no work today".
        raise Forbidden(f"the {view} view needs a manager")
    keys = decode_cursor(cursor) if cursor else None
    size = min(limit, 100)
    arguments: list[Any] = [ctx.user.id, status_filter, q, channel_id]
    if keys is not None:
        arguments.extend(keys)
    # One more than asked, to know whether there is another page.
    arguments.append(size + 1)
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        rows = await conn.fetch(list_sql(view, with_cursor=keys is not None), *arguments)
    page, has_more = rows[:size], len(rows) > size
    now = datetime.now(UTC)
    return {
        "data": [_summary(row, now) for row in page],
        "next_cursor": encode_cursor(page[-1]) if has_more and page else None,
    }
```

`_summary(row, now)` is the one mapping from a database row to `ConversationSummary`: it builds the
nested `contact`, `assignee`, `channel` and `team` objects, calls `_preview(row)` and
`_sla_state(...)`, and is used by the thread routes too so the list and the detail can never disagree
about a conversation.

`_FOREVER` and `_NEVER` exist only for `encode_cursor`; the first page passes no cursor arguments at
all, because asyncpg rejects a parameter the query does not mention.

Counts:

```python
@router.get("/counts")
async def conversation_counts(ctx: Ctx) -> dict[str, dict[str, int]]:
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        return {
            view: dict(
                await conn.fetchrow(COUNTS.format(view=_VIEW_SQL[view]), ctx.tenant_id, ctx.user.id)
            )
            for view in VIEWS_BY_SCOPE[ctx.scope]
        }
```

- [ ] **Step 5: Run the tests**

Run: `cd apps/api && uv run pytest tests/test_inbox_list.py -v && uv run mypy src`
Expected: PASS. If ordering fails, check `coalesce(waiting_since, 'infinity')` — a conversation
nobody waits on must sort last, not first.

- [ ] **Step 6: Commit**

```bash
git add apps/api/src/dealerai/db/queries apps/api/src/dealerai/routes/inbox.py apps/api/tests/test_inbox_list.py
git commit -m "feat(sales): the inbox queue, its views and its counts"
```

---

## Task 7: The thread and what you can do to it

**Files:**
- Modify: `apps/api/src/dealerai/db/queries/inbox.py`, `apps/api/src/dealerai/routes/inbox.py`
- Create: `apps/api/tests/test_inbox_thread.py`

Six routes, all small, all on a conversation the caller can already see: read it, read its messages,
add an internal note, move the read cursor, assign it, change its status. The Message shape is the
one in [`contract/types.ts`](../contract/types.ts) — every WhatsApp type in one object, so the thread
renders from one list.

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/test_inbox_thread.py
"""Opening a conversation, and the four things a salesperson does to it."""

from __future__ import annotations

from fastapi.testclient import TestClient

from conftest import MANAGER, SALES_1, SALES_2, TENANT_B, USER_B


def test_the_thread_comes_back_newest_last_with_every_type(client: TestClient, conversation: str) -> None:
    body = client.get(f"/v1/conversations/{conversation}/messages", headers=_auth(SALES_1)).json()
    kinds = [(m["type"], m["origin"]) for m in body["data"]]
    assert ("audio", "customer") in kinds
    assert ("text", "inbox") in kinds
    voice = next(m for m in body["data"] if m["type"] == "audio")
    assert voice["transcript"]["text"]
    assert voice["attachment"]["url"].startswith("/v1/media/"), "media is served through a link"


def test_an_internal_note_is_never_sent(client: TestClient, conversation: str) -> None:
    created = client.post(
        f"/v1/conversations/{conversation}/notes",
        json={"text": "He asked for a discount last year."},
        headers=_auth(SALES_1),
    )
    assert created.status_code == 201
    assert created.json()["kind"] == "note"
    assert client.get(
        f"/v1/conversations/{conversation}/messages", headers=_auth(SALES_1)
    ).json()["data"][-1]["kind"] == "note"
    # Nothing was queued for WhatsApp.
    assert created.json()["status"] is None


def test_opening_marks_it_read_for_me_only(client: TestClient, conversation: str) -> None:
    assert client.post(f"/v1/conversations/{conversation}/read", headers=_auth(SALES_1)).status_code == 204
    mine = client.get("/v1/conversations?view=mine", headers=_auth(SALES_1)).json()["data"]
    assert next(row for row in mine if row["id"] == conversation)["unread_count"] == 0
    manager = client.get("/v1/conversations?view=team", headers=_auth(MANAGER)).json()["data"]
    assert next(row for row in manager if row["id"] == conversation)["unread_count"] > 0


def test_a_salesperson_can_claim_an_unassigned_conversation(
    client: TestClient, unassigned: str
) -> None:
    response = client.post(
        f"/v1/conversations/{unassigned}/assign",
        json={"user_id": str(SALES_1)},
        headers=_auth(SALES_1),
    )
    assert response.status_code == 200
    assert response.json()["assignee"]["id"] == str(SALES_1)


def test_a_salesperson_cannot_hand_it_to_someone_else(client: TestClient, unassigned: str) -> None:
    """Claiming is not assigning: inbox.assign is a manager's permission."""
    response = client.post(
        f"/v1/conversations/{unassigned}/assign",
        json={"user_id": str(SALES_2)},
        headers=_auth(SALES_1),
    )
    assert response.status_code == 403


def test_a_manager_may_assign_anyone(client: TestClient, unassigned: str) -> None:
    response = client.post(
        f"/v1/conversations/{unassigned}/assign",
        json={"user_id": str(SALES_2)},
        headers=_auth(MANAGER),
    )
    assert response.status_code == 200
    assert response.json()["assignee"]["id"] == str(SALES_2)


def test_closing_stops_the_timer_and_leaves_a_line(client: TestClient, conversation: str) -> None:
    response = client.post(
        f"/v1/conversations/{conversation}/status", json={"status": "closed"}, headers=_auth(SALES_1)
    )
    assert response.status_code == 200
    assert response.json()["waiting_since"] is None
    messages = client.get(
        f"/v1/conversations/{conversation}/messages", headers=_auth(SALES_1)
    ).json()["data"]
    assert messages[-1]["event"]["type"] == "closed"


def test_another_tenant_sees_none_of_it(client: TestClient, conversation: str) -> None:
    for path in ("", "/messages"):
        assert client.get(
            f"/v1/conversations/{conversation}{path}",
            headers={**_auth(USER_B, TENANT_B)},
        ).status_code == 404
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd apps/api && uv run pytest tests/test_inbox_thread.py -v`
Expected: FAIL — 404 on every route.

- [ ] **Step 3: Write the routes**

All six live in `routes/inbox.py`. The details that matter:

```python
@router.get("/{conversation_id}", response_model=Conversation)
async def get_conversation(ctx: Ctx, conversation_id: UUID) -> dict[str, Any]:
    """The summary plus the rolling summary; the lead arrives with S3."""


@router.get("/{conversation_id}/messages", response_model=MessagePage)
async def list_messages(ctx: Ctx, conversation_id: UUID, cursor: str | None = None,
                        limit: int = 50) -> dict[str, Any]:
    """Newest last, older pages walking backwards — the thread scrolls up.

    The API returns oldest-first within a page so the client can append without
    reversing, and `next_cursor` points further into the past.
    """


@router.post("/{conversation_id}/notes", status_code=201, response_model=MessageOut)
async def add_note(ctx: Ctx, conversation_id: UUID, body: NoteIn) -> dict[str, Any]:
    """kind='note', origin='inbox', status null. It never reaches the connector:
    there is no send event, which is the only reason it cannot be sent."""


@router.post("/{conversation_id}/read", status_code=204)
async def mark_conversation_read(ctx: Ctx, conversation_id: UUID) -> Response:
    """upsert conversation_reads … last_read_at = now(). One person's cursor."""


@router.post("/{conversation_id}/assign", response_model=ConversationSummary)
async def assign_conversation(ctx: Ctx, conversation_id: UUID, body: AssignIn) -> dict[str, Any]:
    """Claiming yourself needs nothing; assigning anyone else needs inbox.assign.

    if body.user_id != ctx.user.id and not ctx.may("inbox.assign"):
        raise Forbidden("assigning to someone else needs the inbox.assign permission")
    """


@router.post("/{conversation_id}/status", response_model=ConversationSummary)
async def set_status(ctx: Ctx, conversation_id: UUID, body: StatusIn) -> dict[str, Any]:
    """open | closed | spam. Closing clears waiting_since and sla_due_at — the
    timer is about a customer waiting for an answer, and a closed conversation
    is an answer."""
```

One more route, on the messages prefix rather than the conversation's
([06](../06-api-contract.md) §3), because the thread's Retry button needs it:

```python
@router.post("/messages/{message_id}/retry", response_model=MessageOut, status_code=202)
async def retry_message(
    message_id: UUID,
    ctx: Annotated[TenantContext, Depends(require_permission("inbox.send"))],
) -> dict[str, Any]:
    """Send a failed message again, as itself.

    Only from `failed`: a message in `sending` is the ambiguous case the watchdog
    owns, and re-queueing it is exactly the double send S1 removed. The row keeps
    its id and its idempotency key, so the thread does not grow a second bubble.
    """
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        row = await conn.fetchrow(
            """update messages set status = 'queued', error = null, locked_at = null
               where id = $1 and status = 'failed' and direction = 'out'
               returning id, conversation_id""",
            message_id,
        )
        if row is None:
            raise NotFound("no failed message to retry")
        await emit(
            conn,
            "whatsapp.send_requested",
            {"message_id": str(message_id)},
            tenant_id=ctx.tenant_id,
            dedupe_key=f"send:{message_id}:retry:{int(datetime.now(UTC).timestamp())}",
            priority=10,
        )
    ...
```

A test belongs with it: a `sending` message is **not** retryable (404), and a retried message keeps
its id.

Every one of them ends with the same two lines: an event line in the thread (`_event_line` from the
handler module — move it to `db/queries/inbox.py` so both can use it) and a re-read of the summary
row, so the client gets the same shape the list gives.

The `Message` DTO (contract §3) is built once, in `routes/inbox.py`:

```python
class Attachment(BaseModel):
    url: str
    mime: str
    filename: str | None
    size_bytes: int | None
    duration_s: float | None
    width: int | None
    height: int | None


class MessageOut(BaseModel):
    id: UUID
    conversation_id: UUID
    kind: Literal["message", "note", "event"]
    type: str
    direction: Literal["in", "out"]
    origin: str
    author: UserRef | None
    text: str | None
    attachment: Attachment | None
    transcript: dict[str, Any] | None
    location: dict[str, Any] | None
    template: dict[str, Any] | None
    reply_to: dict[str, Any] | None
    reactions: list[dict[str, Any]]
    status: str | None
    error: dict[str, Any] | None
    event: dict[str, Any] | None
    referral: dict[str, Any] | None
    created_at: datetime
```

`status` is null for inbound and for notes: the ticks belong to messages we sent.

- [ ] **Step 4: Run the tests**

Run: `cd apps/api && uv run pytest tests/test_inbox_thread.py tests/test_inbox_list.py -v`
Expected: PASS except the media URL assertion, which Task 8 satisfies. Leave that one failing and
come back to it — or write Task 8 first if a red test between commits bothers you.

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/dealerai apps/api/tests/test_inbox_thread.py
git commit -m "feat(sales): the conversation thread, notes, read cursor, assignment and status"
```

---

## Task 8: A photo the browser can show, and nobody else can

**Files:**
- Create: `apps/api/src/dealerai/media/links.py`
- Create: `apps/api/src/dealerai/routes/media.py`
- Modify: `apps/api/src/dealerai/main.py`, `routes/inbox.py`
- Create: `apps/api/tests/test_media_links.py`

A browser cannot put an `Authorization` header on `<img src>`, which is the only reason signed links
exist. Signing them ourselves works for both back ends — Supabase Storage and the local disk — and
keeps customer media private without handing the browser a storage key.

The link is the capability, so it is short-lived, scoped to one object, and carries its own tenant in
the path it signs.

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/test_media_links.py
"""A link to one object, for one hour, for whoever has it — and nothing else."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dealerai.config import get_settings
from dealerai.core.security import Unauthenticated
from dealerai.main import app
from dealerai.media.links import sign, verify

PATH = "11111111-0000-4000-8000-000000000001/messages/2026/09/abc.ogg"


@pytest.fixture(autouse=True)
def _secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "supabase_jwt_secret", "s" * 40)


def test_a_link_round_trips() -> None:
    assert verify(sign(PATH)) == PATH


def test_an_expired_link_is_refused() -> None:
    with pytest.raises(Unauthenticated):
        verify(sign(PATH, expires_in=timedelta(seconds=-1)))


def test_a_link_cannot_be_pointed_at_another_object() -> None:
    token = sign(PATH)
    tampered = token.replace("abc.ogg", "xyz.ogg")
    with pytest.raises(Unauthenticated):
        verify(tampered)


def test_a_link_signed_with_another_key_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    token = sign(PATH)
    monkeypatch.setattr(get_settings(), "supabase_jwt_secret", "d" * 40)
    with pytest.raises(Unauthenticated):
        verify(token)


def test_the_route_serves_the_bytes_and_refuses_a_bad_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "storage_dir", str(tmp_path))
    target = tmp_path / PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"OggS voice")

    with TestClient(app) as client:
        ok = client.get(f"/v1/media/{sign(PATH)}")
        assert ok.status_code == 200
        assert ok.content == b"OggS voice"
        assert ok.headers["cache-control"].startswith("private")
        assert client.get("/v1/media/not-a-link").status_code == 401
```

- [ ] **Step 2: Write the signer**

```python
# apps/api/src/dealerai/media/links.py
"""Short-lived links to private stored objects.

The link is the capability: it names one object, expires within the hour, and is
signed with the project's JWT secret under its own prefix, so a media link can
never be replayed as a session token or the other way round.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import time
from datetime import timedelta

from ..config import get_settings
from ..core.security import AuthUnavailable, Unauthenticated

#: Domain separation: the same secret signs sessions.
_PREFIX = b"dealerai/media-link/v1:"
DEFAULT_TTL = timedelta(hours=1)


def _key() -> bytes:
    secret = get_settings().supabase_jwt_secret
    if not secret:
        raise AuthUnavailable("SUPABASE_JWT_SECRET is not set")
    return secret.encode()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign(storage_path: str, *, expires_in: timedelta = DEFAULT_TTL) -> str:
    expiry = int(time.time() + expires_in.total_seconds())
    body = f"{expiry}:{storage_path}".encode()
    signature = hmac.new(_key(), _PREFIX + body, hashlib.sha256).digest()
    return f"{_b64(body)}.{_b64(signature)}"


def verify(token: str) -> str:
    """The storage path this link names, or Unauthenticated. Never leaks which check failed."""
    try:
        encoded_body, encoded_signature = token.split(".", 1)
        body = _unb64(encoded_body)
        signature = _unb64(encoded_signature)
    except (ValueError, binascii.Error) as exc:
        raise Unauthenticated("invalid media link") from exc

    expected = hmac.new(_key(), _PREFIX + body, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected):
        raise Unauthenticated("invalid media link")

    expiry, _, storage_path = body.decode().partition(":")
    if not storage_path or int(expiry) < time.time():
        raise Unauthenticated("this media link has expired")
    return storage_path
```

- [ ] **Step 3: Write the route**

```python
# apps/api/src/dealerai/routes/media.py
"""Serving a stored object to a browser that holds a signed link."""

from __future__ import annotations

import mimetypes

from fastapi import APIRouter, Response

from ..media import storage
from ..media.links import verify

router = APIRouter(prefix="/v1/media", tags=["media"])


@router.get("/{token}")
async def get_object(token: str) -> Response:
    """No X-Tenant-Id and no bearer token: the link is the authorisation.

    ponytail: the whole object is read into memory before it is answered. WhatsApp
    caps media at 100 MB and a dealer's are photos and voice notes. Upgrade
    trigger: video attachments in real use — then stream it through.
    """
    storage_path = verify(token)
    data = await storage.download(storage_path)
    mime, _ = mimetypes.guess_type(storage_path)
    return Response(
        content=data,
        media_type=mime or "application/octet-stream",
        headers={"Cache-Control": "private, max-age=3600", "Content-Disposition": "inline"},
    )
```

In `routes/inbox.py`, the `Message` DTO builds `attachment.url` with `sign(media["storage_path"])`
for every stored asset, and leaves `attachment` null while the media is still `pending` or `failed`
— the thread shows a placeholder for those, not a broken image.

Mount the router in `main.py`.

- [ ] **Step 4: Run the tests**

Run: `cd apps/api && uv run pytest tests/test_media_links.py tests/test_inbox_thread.py -v`
Expected: PASS, including the thread test's `/v1/media/` assertion from Task 7.

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/dealerai apps/api/tests/test_media_links.py
git commit -m "feat(sales): signed links for private message media"
```

---

## Task 9: The screen keeps up by itself

**Files:**
- Create: `apps/api/src/dealerai/realtime.py`
- Create: `apps/api/src/dealerai/routes/stream.py`
- Modify: `apps/api/src/dealerai/db/session.py`, `main.py`
- Create: `apps/api/tests/test_realtime.py`

One LISTEN connection per API process, fanned out to the streams open on it. The payload is ids, so
the browser refetches through REST and a missed event costs a request rather than a wrong screen.

The visibility check happens here, in memory, against the ids in the payload: a stream must never
carry a colleague's conversation to a salesperson just because the database woke everyone up.

- [ ] **Step 1: Write the failing test**

```python
# apps/api/tests/test_realtime.py
"""Who hears which live update, and what a stream sends when nothing happens."""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from conftest import MANAGER, SALES_1, SALES_2, TEAM_LOCAL, TENANT_A, TENANT_B
from dealerai.realtime import Hub, Subscriber

CONVERSATION = uuid.uuid4()


def _payload(**overrides: object) -> str:
    payload = {
        "tenant_id": str(TENANT_A),
        "type": "message.created",
        "id": str(uuid.uuid4()),
        "conversation_id": str(CONVERSATION),
        "owner_id": str(SALES_1),
        "assigned_to": str(SALES_1),
        "team_id": str(TEAM_LOCAL),
        "user_id": None,
    }
    payload.update(overrides)  # type: ignore[arg-type]
    return json.dumps(payload)


def _subscriber(user_id: uuid.UUID, scope: str, **kwargs: object) -> Subscriber:
    return Subscriber(
        tenant_id=TENANT_A,
        user_id=user_id,
        scope=scope,
        visible_owner_ids=kwargs.get("visible", {SALES_1}),  # type: ignore[arg-type]
        team_ids={TEAM_LOCAL},
    )


async def test_another_tenant_never_hears_anything() -> None:
    hub = Hub()
    listener = hub.subscribe(_subscriber(SALES_1, "own"))
    hub.publish(_payload(tenant_id=str(TENANT_B)))
    assert listener.queue.empty()


async def test_a_salesperson_hears_their_own_conversation() -> None:
    hub = Hub()
    listener = hub.subscribe(_subscriber(SALES_1, "own"))
    hub.publish(_payload())
    assert json.loads(await listener.queue.get())["conversation_id"] == str(CONVERSATION)


async def test_a_salesperson_does_not_hear_a_colleagues(self_check: None = None) -> None:
    hub = Hub()
    listener = hub.subscribe(_subscriber(SALES_2, "own", visible={SALES_2}))
    hub.publish(_payload())
    assert listener.queue.empty(), "a live update leaked across salespeople"


async def test_a_manager_hears_their_teams_unassigned_queue() -> None:
    hub = Hub()
    listener = hub.subscribe(_subscriber(MANAGER, "team", visible={SALES_1, SALES_2}))
    hub.publish(_payload(owner_id=None, assigned_to=None))
    assert not listener.queue.empty()


async def test_a_notification_reaches_only_its_person() -> None:
    hub = Hub()
    mine = hub.subscribe(_subscriber(SALES_1, "own"))
    theirs = hub.subscribe(_subscriber(SALES_2, "own", visible={SALES_2}))
    hub.publish(_payload(type="notification.created", user_id=str(SALES_1),
                         conversation_id=None, owner_id=None, assigned_to=None))
    assert not mine.queue.empty()
    assert theirs.queue.empty()


async def test_a_slow_reader_is_dropped_rather_than_remembered() -> None:
    """A browser tab that stopped reading must not grow a queue forever."""
    hub = Hub(max_queued=2)
    listener = hub.subscribe(_subscriber(SALES_1, "own"))
    for _ in range(5):
        hub.publish(_payload())
    assert listener.queue.qsize() == 2
    assert listener.dropped >= 3
```

- [ ] **Step 2: Write the hub**

```python
# apps/api/src/dealerai/realtime.py
"""Postgres NOTIFY to open SSE streams, one LISTEN connection per process.

The event is a nudge, never data: it carries ids, and the browser refetches over
REST. That is what makes a missed event cost a request instead of showing a
stale screen — and what keeps customer messages out of Postgres's notification
queue, which is global to the database.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import structlog

log = structlog.get_logger()

#: How many events a single browser tab may fall behind before we drop the
#: oldest. A tab that stopped reading is a tab that will refetch on reconnect.
MAX_QUEUED = 100


@dataclass
class Subscriber:
    tenant_id: UUID
    user_id: UUID
    scope: str
    #: Owner ids this person may see, from app.visible_owner_ids(); empty means
    #: "no owner filter" only when the scope is all.
    visible_owner_ids: set[UUID]
    team_ids: set[UUID]
    queue: asyncio.Queue[str] = field(default_factory=asyncio.Queue)
    dropped: int = 0

    def may_see(self, event: dict[str, Any]) -> bool:
        if str(event.get("tenant_id")) != str(self.tenant_id):
            return False
        for_user = event.get("user_id")
        if for_user:  # a notification belongs to exactly one person
            return str(for_user) == str(self.user_id)
        if self.scope == "all":
            return True
        owner = event.get("owner_id")
        assignee = event.get("assigned_to")
        if assignee and str(assignee) == str(self.user_id):
            return True
        if owner and UUID(str(owner)) in self.visible_owner_ids:
            return True
        # The team's unassigned queue, the same rule app.pool_visible() applies.
        team = event.get("team_id")
        return not owner and not assignee and bool(team) and UUID(str(team)) in self.team_ids


class Hub:
    """Every open stream on this process."""

    def __init__(self, max_queued: int = MAX_QUEUED) -> None:
        self._subscribers: set[Subscriber] = set()
        self._max_queued = max_queued

    def subscribe(self, subscriber: Subscriber) -> Subscriber:
        self._subscribers.add(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: Subscriber) -> None:
        self._subscribers.discard(subscriber)

    @property
    def open_streams(self) -> int:
        return len(self._subscribers)

    def publish(self, raw: str) -> None:
        """Called by the LISTEN callback. Never blocks: a slow tab loses events, not the process."""
        try:
            event = json.loads(raw)
        except ValueError:
            log.warning("realtime_payload_unreadable")
            return
        for subscriber in self._subscribers:
            if not subscriber.may_see(event):
                continue
            if subscriber.queue.qsize() >= self._max_queued:
                subscriber.queue.get_nowait()
                subscriber.dropped += 1
            subscriber.queue.put_nowait(raw)


hub = Hub()


async def listen(stop: asyncio.Event) -> None:
    """Hold one connection on LISTEN 'rt' for the life of the process.

    Reconnects with backoff: a dropped listener means the screens stop moving,
    and they must start again without a deploy.
    """
    from .db import session  # imported here: only db.session opens connections

    delay = 1.0
    while not stop.is_set():
        try:
            async with session.listen_connection() as conn:
                await conn.add_listener("rt", lambda *args: hub.publish(str(args[-1])))
                log.info("realtime_listening")
                delay = 1.0
                await stop.wait()
                await conn.remove_listener("rt", lambda *args: None)
        except Exception:
            log.exception("realtime_listener_lost", retry_in=delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30.0)
```

Two things to get right while implementing: keep one named callback so `remove_listener` can remove
it, and give `listen_connection()` a home in `db/session.py` — it is the only module allowed to take
a connection, and a LISTEN connection is held for the life of the process rather than per request:

```python
@contextlib.asynccontextmanager
async def listen_connection() -> AsyncIterator[asyncpg.Connection]:
    """One long-lived connection for LISTEN.

    It is held out of the pool for the whole process, so db_pool_max must be at
    least two. A transaction-pooled connection cannot LISTEN at all, which is why
    deployment points the API at the session pooler (docs/sales/01 § 6).
    """
    pool = _require_pool()
    conn = await pool.acquire()
    try:
        yield conn
    finally:
        await pool.release(conn)
```

- [ ] **Step 3: Write the stream route**

```python
# apps/api/src/dealerai/routes/stream.py
"""GET /v1/stream — the one SSE connection a browser tab opens."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from ..db.session import tenant_session
from ..deps import Ctx
from ..realtime import Subscriber, hub

router = APIRouter(prefix="/v1", tags=["stream"])

#: A comment every fifteen seconds keeps proxies from closing an idle stream.
HEARTBEAT_SECONDS = 15


@router.get("/stream")
async def stream(ctx: Ctx) -> StreamingResponse:
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        owners = await conn.fetchval("select app.visible_owner_ids()")
        teams = await conn.fetchval("select app.my_team_ids()")
    subscriber = hub.subscribe(
        Subscriber(
            tenant_id=ctx.tenant_id,
            user_id=ctx.user.id,
            scope=ctx.scope,
            visible_owner_ids=set(owners or []),
            team_ids=set(teams or []),
        )
    )

    async def events() -> AsyncIterator[str]:
        yield ": connected\n\n"
        try:
            while True:
                try:
                    raw = await asyncio.wait_for(subscriber.queue.get(), HEARTBEAT_SECONDS)
                except TimeoutError:
                    yield ": heartbeat\n\n"
                    continue
                event = json.loads(raw)
                yield f"event: {event['type']}\ndata: {raw}\n\n"
        finally:
            hub.unsubscribe(subscriber)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
```

Start the listener in `main.py`'s lifespan (`asyncio.create_task(realtime.listen(stop))`, cancelled
on shutdown), and add `"streams": hub.open_streams` to `/internal/health` — [01](../01-architecture.md) §8
asks for it and it costs one line.

- [ ] **Step 4: Run the tests**

Run: `cd apps/api && uv run pytest tests/test_realtime.py -v && uv run mypy src`
Expected: PASS. Delete the stray `self_check` parameter in the colleague test while implementing.

- [ ] **Step 5: Prove it end to end, once, by hand**

```bash
npm run api          # one terminal
npm run worker       # another
```

Then with a dev token (`/dev-login` in the browser, copy the cookie) or a minted one:

```bash
curl -N -H "Authorization: Bearer $TOKEN" -H "X-Tenant-Id: $TENANT" http://localhost:8000/v1/stream
```

Send `npm run wa:simulate inbound -- --text "Any Land Cruiser in white?"` from a third terminal and
watch `event: message.created` arrive. This is the moment to find out that the trigger, the listener
and the filter agree — not in the browser.

- [ ] **Step 6: Commit**

```bash
git add apps/api/src/dealerai apps/api/tests/test_realtime.py
git commit -m "feat(sales): live updates from Postgres to an SSE stream"
```

---

## Task 10: The browser's side of the contract

**Files:**
- Modify: `apps/web/lib/api/keys.ts`, `apps/web/lib/api/hooks.ts`
- Create: `apps/web/lib/live.tsx`
- Modify: `apps/web/lib/api/client.ts` (export the base URL)
- Create: `apps/web/lib/api/hooks.test.ts`
- Modify: `apps/web/app/[tenant]/layout.tsx`

Every screen in this slice reads through these hooks; no component calls `fetch`. The live reader
mounts once and only invalidates — it never writes data into the cache, so a live update and a
refetch can never disagree.

- [ ] **Step 1: Regenerate the types**

Run: `npm run api-types`
Expected: `apps/web/lib/api/schema.ts` grows the conversations, notifications, media and stream
paths. Commit them with this task; CI fails on drift.

- [ ] **Step 2: Add the keys**

```ts
// apps/web/lib/api/keys.ts
/** Every query key in one place, so an invalidation can never miss a spelling. */
export const keys = {
  me: (tenantId: string) => ["me", tenantId] as const,
  members: (tenantId: string) => ["members", tenantId] as const,
  teams: (tenantId: string) => ["teams", tenantId] as const,
  conversations: (tenantId: string, view: string, filters: string) =>
    ["conversations", tenantId, view, filters] as const,
  conversationList: (tenantId: string) => ["conversations", tenantId] as const,
  counts: (tenantId: string) => ["conversation-counts", tenantId] as const,
  conversation: (tenantId: string, id: string) => ["conversation", tenantId, id] as const,
  messages: (tenantId: string, id: string) => ["messages", tenantId, id] as const,
  notifications: (tenantId: string) => ["notifications", tenantId] as const,
};
```

- [ ] **Step 3: Add the hooks**

In `apps/web/lib/api/hooks.ts`, following the two that exist:

```ts
export type ConversationView = "mine" | "unassigned" | "team" | "all";
export type InboxFilters = { status: string; q: string; view: ConversationView };

export function useConversations(filters: InboxFilters) {
  const { api, tenantId, header } = useTenantApi();
  return useInfiniteQuery({
    queryKey: keys.conversations(tenantId, filters.view, `${filters.status}|${filters.q}`),
    initialPageParam: undefined as string | undefined,
    queryFn: async ({ pageParam }) =>
      unwrap(
        await api.GET("/v1/conversations", {
          params: {
            header,
            query: { view: filters.view, status: filters.status, q: filters.q, cursor: pageParam },
          },
        }),
      ),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
  });
}

export function useSendMessage(conversationId: string) {
  const { api, tenantId, header } = useTenantApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (text: string) =>
      unwrap(
        await api.POST("/v1/conversations/{conversation_id}/messages", {
          params: { header: { ...header, "Idempotency-Key": crypto.randomUUID() },
                    path: { conversation_id: conversationId } },
          body: { text },
        }),
      ),
    // The reply appears the moment it is typed; the server's row replaces it.
    onMutate: async (text) => {
      const key = keys.messages(tenantId, conversationId);
      await queryClient.cancelQueries({ queryKey: key });
      const previous = queryClient.getQueryData(key);
      queryClient.setQueryData(key, (old: unknown) => appendPending(old, text));
      return { previous };
    },
    onError: (_error, _text, context) => {
      queryClient.setQueryData(keys.messages(tenantId, conversationId), context?.previous);
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: keys.messages(tenantId, conversationId) });
      queryClient.invalidateQueries({ queryKey: keys.conversationList(tenantId) });
    },
  });
}
```

Write the same shape for `useConversationCounts`, `useConversation`, `useMessages` (infinite,
backwards), `useAddNote`, `useMarkRead`, `useAssign`, `useSetStatus`, `useNotifications` and
`useMarkNotificationsRead`. `appendPending` is a small pure helper in the same file — export it, and
unit-test it in `hooks.test.ts` along with the optimistic rollback, because those two are the only
parts of this file with logic rather than wiring.

- [ ] **Step 4: Write the live reader**

```tsx
// apps/web/lib/live.tsx
"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { API_BASE } from "@/lib/api/client";
import { useTenantApi } from "@/lib/api/context";
import { keys } from "@/lib/api/keys";
import { getBrowserAccessToken } from "@/lib/auth/token";

/** What each live event makes stale. Ids only — the screen refetches the truth. */
type LiveEvent = { type: string; conversation_id?: string | null };

/**
 * One SSE connection per tab, opened with fetch because the native EventSource
 * cannot send an Authorization header. It only invalidates: a live update that
 * wrote into the cache could disagree with the next refetch, and the refetch
 * would win half the time.
 */
export function useLiveEvents(): void {
  const { tenantId } = useTenantApi();
  const queryClient = useQueryClient();

  useEffect(() => {
    const controller = new AbortController();
    let attempt = 0;
    let stopped = false;

    const invalidate = (event: LiveEvent) => {
      const conversationId = event.conversation_id ?? undefined;
      if (event.type.startsWith("message.") && conversationId) {
        queryClient.invalidateQueries({ queryKey: keys.messages(tenantId, conversationId) });
      }
      if (conversationId) {
        queryClient.invalidateQueries({ queryKey: keys.conversation(tenantId, conversationId) });
      }
      if (event.type === "notification.created") {
        queryClient.invalidateQueries({ queryKey: keys.notifications(tenantId) });
      }
      queryClient.invalidateQueries({ queryKey: keys.conversationList(tenantId) });
      queryClient.invalidateQueries({ queryKey: keys.counts(tenantId) });
    };

    const read = async () => {
      while (!stopped) {
        try {
          const token = await getBrowserAccessToken();
          const response = await fetch(`${API_BASE}/v1/stream`, {
            headers: { Authorization: `Bearer ${token ?? ""}`, "X-Tenant-Id": tenantId },
            signal: controller.signal,
          });
          if (!response.ok || !response.body) throw new Error(`stream ${response.status}`);

          // Reconnected: whatever happened while we were away is already in the
          // database, so refetch rather than replay.
          if (attempt > 0) await queryClient.invalidateQueries();
          attempt = 0;

          const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
          let buffer = "";
          for (;;) {
            const { value, done } = await reader.read();
            if (done) break;
            buffer += value;
            const frames = buffer.split("\n\n");
            buffer = frames.pop() ?? "";
            for (const frame of frames) {
              const data = frame
                .split("\n")
                .find((line) => line.startsWith("data:"))
                ?.slice(5)
                .trim();
              if (data) invalidate(JSON.parse(data) as LiveEvent);
            }
          }
        } catch (error) {
          if (controller.signal.aborted) return;
          // Backoff with jitter: a restarted API must not be hit by every tab at once.
          const wait = Math.min(1000 * 2 ** attempt++, 30_000) * (0.5 + Math.random());
          await new Promise((resolve) => setTimeout(resolve, wait));
        }
      }
    };

    void read();
    return () => {
      stopped = true;
      controller.abort();
    };
  }, [queryClient, tenantId]);
}
```

Export `API_BASE` from `lib/api/client.ts` (it is already the module's `BASE`), and call
`useLiveEvents()` from a small client component mounted in `app/[tenant]/providers.tsx`.

- [ ] **Step 5: Run the web checks**

Run: `npm run check:web`
Expected: typecheck, RTL check, lint and Vitest pass.

- [ ] **Step 6: Commit**

```bash
git add apps/web package.json
git commit -m "feat(web): inbox queries, optimistic send and the live event reader"
```

---

## Task 11: The queue on screen

**Files:**
- Modify: `apps/web/app/[tenant]/inbox/page.tsx`
- Create: `apps/web/app/[tenant]/inbox/layout.tsx`
- Create: `apps/web/components/inbox/{ConversationList,ConversationRow,InboxTabs,InboxFilters,WaitingTimer}.tsx`
- Modify: `apps/web/messages/{en,ar}.ts`
- Create: `apps/web/components/inbox/ConversationRow.test.tsx`

The row is where a salesperson decides what to do next, so it earns its density: who, what they said,
how long they have waited, and whether anyone has it. The timer is the part a manager watches.

- [ ] **Step 1: Write the failing test**

```tsx
// apps/web/components/inbox/ConversationRow.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ConversationRow } from "./ConversationRow";
import { LocaleProvider } from "@/lib/i18n-client";

const base = {
  id: "c1",
  contact: { id: "k1", name: "Karim Benali", country: "DZ", language: "fr", tags: [], owner: null,
             last_seen_at: null },
  channel: { id: "ch", platform: "whatsapp", name: "Pollux" },
  status: "open",
  assignee: null,
  team: null,
  last_message: { preview: "Le prix pour Oran ?", type: "text", direction: "in",
                  origin: "customer", at: new Date().toISOString() },
  unread_count: 2,
  waiting_since: new Date(Date.now() - 12 * 60_000).toISOString(),
  sla_due_at: new Date(Date.now() - 60_000).toISOString(),
  sla_state: "breached",
  window_expires_at: null,
  has_ai_draft: false,
};

const show = (row: typeof base) =>
  render(
    <LocaleProvider locale="en">
      <ConversationRow conversation={row} href="/t/inbox/c1" active={false} />
    </LocaleProvider>,
  );

describe("ConversationRow", () => {
  it("shows who is waiting, for how long, and what they said", () => {
    show(base);
    expect(screen.getByText("Karim Benali")).toBeTruthy();
    expect(screen.getByText("Le prix pour Oran ?")).toBeTruthy();
    expect(screen.getByText(/12m/)).toBeTruthy();
    expect(screen.getByText("2")).toBeTruthy();
  });

  it("says a missed target out loud, not only in colour", () => {
    show(base);
    // Colour alone fails a colour-blind manager and every screen reader.
    expect(screen.getByLabelText(/waiting/i).textContent).toMatch(/12m/);
    expect(screen.getByRole("listitem").getAttribute("data-sla")).toBe("breached");
  });

  it("marks our own last message as ours", () => {
    show({ ...base, last_message: { ...base.last_message, direction: "out", origin: "inbox" } });
    expect(screen.getByText(/^You:/)).toBeTruthy();
  });

  it("says a voice note is a voice note", () => {
    show({ ...base, last_message: { ...base.last_message, type: "audio", preview: "Voice note" } });
    expect(screen.getByText("Voice note")).toBeTruthy();
  });

  it("shows an unassigned conversation as unassigned", () => {
    show(base);
    expect(screen.getByText(/unassigned/i)).toBeTruthy();
  });
});
```

`@testing-library/react` is not installed yet: `npm install -D @testing-library/react @testing-library/dom jsdom --workspace web`
and set `environment: "jsdom"` in `vitest.config.mts`. The existing tests are node-environment pure
functions and keep working.

- [ ] **Step 2: Build the screen**

- `app/[tenant]/inbox/layout.tsx`: two panes on desktop (`lg:grid lg:grid-cols-[360px_1fr]`), one on
  mobile. The list is the page; the thread is the nested route. On mobile the list hides when a
  conversation is open (`lg:block` on the list, route-driven on small screens).
- `page.tsx` stays a server component: it renders `<ConversationList />` and nothing else. First
  paint comes from the server through `lib/api.ts` (the cookie-session helper) and is handed to
  React Query as `initialData` — [07](../07-frontend.md) §2.
- `InboxTabs`: the views the caller may open, from `useMe().scope` — `own` gets Mine and Unassigned.
  The current view lives in the URL (`?view=`), so a link to the queue is a link to the same queue.
- `InboxFilters`: status select (open by default), a search box debounced 300 ms writing `?q=`.
- `ConversationList`: `useConversations`, an `IntersectionObserver` at the end for the next page,
  skeleton rows while loading, an empty state that says what to do next ("Nothing waiting. Take one
  from Unassigned."), and an error state showing `problem.detail` with Retry.
- `WaitingTimer`: `formatDuration` from `lib/format.ts`, `data-sla` on the row, colour **and** text.

Keyboard: `j`/`k` move the selection, `Enter` opens it. Bind on the list container with
`onKeyDown`, not on `window`, so typing in the composer never moves the list.

- [ ] **Step 3: Add the strings**

Every new string goes into `messages/en.ts` and `messages/ar.ts` — `messages.test.ts` fails if the
two drift. The Arabic for the timer reads "ينتظر ١٢ د"; keep the number formatting in `lib/format.ts`
rather than in the component.

- [ ] **Step 4: Run the checks**

Run: `npm run check:web`
Expected: pass, including `check:rtl` — use `ms-*`/`me-*`, never `ml-*`/`mr-*`.

- [ ] **Step 5: Commit**

```bash
git add apps/web
git commit -m "feat(web): the inbox queue, its tabs, filters and waiting timers"
```

---

## Task 12: The conversation

**Files:**
- Create: `apps/web/app/[tenant]/inbox/[conversationId]/page.tsx`
- Create: `apps/web/components/inbox/{Thread,MessageBubble,ThreadHeader,Composer,WindowBanner,AssignControl}.tsx`
- Create: `apps/web/components/inbox/MessageBubble.test.tsx`
- Modify: `apps/web/messages/{en,ar}.ts`

One list renders every WhatsApp type, because the API returns one shape. The two things that must be
impossible: an internal note that looks like a sent message, and a failed message that looks
delivered.

- [ ] **Step 1: Write the failing test**

```tsx
// apps/web/components/inbox/MessageBubble.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MessageBubble } from "./MessageBubble";
import { LocaleProvider } from "@/lib/i18n-client";

const message = {
  id: "m1",
  conversation_id: "c1",
  kind: "message",
  type: "text",
  direction: "in",
  origin: "customer",
  author: null,
  text: "Is the Hilux still available?",
  attachment: null,
  transcript: null,
  location: null,
  template: null,
  reply_to: null,
  reactions: [],
  status: null,
  error: null,
  event: null,
  referral: null,
  created_at: new Date().toISOString(),
};

const show = (overrides: Partial<typeof message>) =>
  render(
    <LocaleProvider locale="en">
      <MessageBubble message={{ ...message, ...overrides }} />
    </LocaleProvider>,
  );

describe("MessageBubble", () => {
  it("shows a voice note's player and its transcript", () => {
    show({
      type: "audio",
      text: null,
      attachment: { url: "/v1/media/abc", mime: "audio/ogg", filename: null, size_bytes: 9620,
                    duration_s: 6, width: null, height: null },
      transcript: { text: "Is the white Land Cruiser available?", language: "en" },
    });
    expect(screen.getByRole("application", { name: /voice note/i })).toBeTruthy();
    // The transcript sits next to the audio, never instead of it: a wrong
    // transcript must be checkable against what was actually said.
    expect(screen.getByText(/white Land Cruiser/)).toBeTruthy();
  });

  it("can never be mistaken for a sent message when it is a note", () => {
    const { container } = show({ kind: "note", direction: "out", origin: "inbox",
                                 text: "He bought from us in 2023." });
    expect(screen.getByText(/internal note/i)).toBeTruthy();
    expect(container.querySelector("[data-kind='note']")).toBeTruthy();
  });

  it("says a message was not delivered, and offers to try again", () => {
    show({ direction: "out", origin: "inbox", status: "failed",
           error: { code: "131047", message: "Window closed — send a template" } });
    expect(screen.getByText(/not delivered/i)).toBeTruthy();
    expect(screen.getByRole("button", { name: /retry/i })).toBeTruthy();
  });

  it("marks a reply typed on the phone as coming from the phone", () => {
    show({ direction: "out", origin: "phone_app", text: "Yes, come at 5." });
    expect(screen.getByText(/sent from phone/i)).toBeTruthy();
  });

  it("renders an unsupported type honestly rather than blankly", () => {
    show({ type: "unsupported", text: null });
    expect(screen.getByText(/open on the phone/i)).toBeTruthy();
  });

  it("shows an event as a line, not a bubble", () => {
    const { container } = show({ kind: "event", event: { type: "assigned", text: "Assigned to Sara" } });
    expect(container.querySelector("[data-kind='event']")).toBeTruthy();
    expect(screen.getByText("Assigned to Sara")).toBeTruthy();
  });
});
```

- [ ] **Step 2: Build the thread**

- `page.tsx` (server component) renders `<Thread conversationId={…} />`.
- `Thread`: `useConversation` + `useMessages`, oldest at the top, `useMarkRead` on mount and when the
  window regains focus, date separators, grouping within five minutes, and `?message=` scrolling to
  and highlighting one message.
- `ThreadHeader`: name, number, channel, `AssignControl` (claim for a salesperson, the member list
  for `inbox.assign`), Close / Reopen / Mark as spam, and `WindowBanner`.
- `WindowBanner`: "Window open · 18h left" from `window_expires_at`, or "Window closed · templates
  only". It is the one thing that explains why the composer is disabled, so it is never subtle.
- `Composer`: auto-growing textarea, Enter sends and Shift+Enter adds a line, a note toggle that
  turns the whole composer yellow, and a template picker when the window is closed
  (`GET /v1/channels/{id}/templates` from S1, variables typed in, preview rendered locally).
  Disabled entirely when the conversation is closed or the channel is not connected.
- Optimistic send from Task 10; a failure rolls back and shows `problem.detail`.

A detail from [08](../08-screens.md) §4 worth keeping: when an echo arrives while someone is typing,
show "A reply was just sent from the phone" above the composer. The live event already tells the
client; the composer just has to notice a new `origin: "phone_app"` message while it has focus.

- [ ] **Step 3: Run the checks**

Run: `npm run check:web`

- [ ] **Step 4: Commit**

```bash
git add apps/web
git commit -m "feat(web): the conversation thread and composer"
```

---

## Task 13: Being told

**Files:**
- Create: `apps/web/components/NotificationsBell.tsx`
- Modify: `apps/web/components/Shell.tsx`, `apps/web/app/[tenant]/providers.tsx`
- Create: `apps/web/components/NotificationsBell.test.tsx`
- Modify: `apps/web/messages/{en,ar}.ts`

The bell is the whole of Phase 1's notification surface — web push arrives in S7. It reads the same
rows the worker writes, so a missed live event costs a refresh, not a missed customer.

- [ ] **Step 1: Build it**

- `NotificationsBell`: `useNotifications`, an unread dot, a popover listing the last 20 with relative
  times, each linking to its `href`, "Mark all read" calling `useMarkNotificationsRead`.
- Opening the popover does not mark anything read — clicking an item does, and so does the button.
  A badge that clears itself teaches people to ignore it.
- The tab title carries the unread count (`document.title = unread ? \`(${unread}) …\` : …`) from the
  same query, in an effect in `providers.tsx`.
- Tests: an unread count renders; clicking an item marks that one read; "Mark all read" empties the
  list; zero notifications shows the empty state rather than an empty popover.

- [ ] **Step 2: Run the checks and commit**

```bash
npm run check:web
git add apps/web
git commit -m "feat(web): the notification bell"
```

---

## Task 14: Prove it, then write it down

**Files:**
- Modify: `docs/sales/README.md`, `docs/sales/plans/s2-inbox.md`
- Modify: `apps/api/src/dealerai/scripts/seed_sales.py` (a queue worth looking at)

S1's lesson, applied: the suite passing is not the exit criterion. **A salesperson answers a customer
in the browser while a manager watches the timer** is the exit criterion.

- [ ] **Step 1: Make the seed look like a Monday morning**

The demo needs a queue with shape: two conversations waiting (one breached, one due soon), one
unassigned in the Local team, one closed, one with a voice note and its transcript, and unread counts
that differ between Ahmed and Sara. Extend `_seed` rather than writing a second script — the same
data serves the S3 screens.

- [ ] **Step 2: Run the full checks**

```bash
COMPOSE_PROJECT_NAME=dealeraios npm run db:reset && npm run db:seed
set -o pipefail; npm run check && npm run check:openapi
```

Expected: ruff, mypy, pytest, the 100%-branch guard suite, web typecheck, `check:rtl`, lint, Vitest,
and no generated-type drift.

- [ ] **Step 3: Run the exit path in a browser**

Three terminals: `npm run api`, `npm run worker`, `npm run web`.

1. Sign in at `/dev-login` as **Ahmed Nasser**. The inbox shows his queue, waiting customers first.
2. In a second browser profile, sign in as **Sara Mansour** and open the same conversation's row in
   Team view. Leave it open.
3. `npm run wa:simulate voice -- --customer AE.seed.1` — Ahmed's list moves the row to the top and
   the unread badge increments **without a refresh**, and so does Sara's.
4. Open the thread: the voice note plays and its transcript reads "Hello, is the white Land Cruiser
   still available? What is your best price?".
5. Reply. The message appears instantly, turns `sent`, the waiting timer disappears on both screens,
   and Sara's row shows the reply as "You:".
6. `npm run wa:simulate status -- --message-id <the wamid> --text delivered` → the tick updates live.
7. Switch the locale to Arabic: the thread mirrors, the timer reads right to left, and the composer
   stays on the correct side. At 360 px the list and thread are separate screens.

Anything that does not happen is a bug in this slice, not a note for later.

- [ ] **Step 4: Record it**

In `docs/sales/README.md`, replace the Code row:

```markdown
| Code | **S2 inbox complete** on `sales/phase-1`: the queue with views and counts, the thread with every message type, notes, assignment, read cursors, business-hours response targets, notifications and live updates over SSE. Next: S3, the CRM |
```

Add a `## Review` section to this file the way [s1-whatsapp.md](s1-whatsapp.md) has one: what the
exit run showed, what was deliberately left, and anything found while running it.

- [ ] **Step 5: Commit**

```bash
git add docs/sales apps/api/src/dealerai/scripts/seed_sales.py
git commit -m "docs(sales): S2 inbox complete, with the exit run recorded"
```

---

## Spec coverage

| Requirement | Where |
|---|---|
| `GET /v1/conversations`, views, order, search ([06](../06-api-contract.md) §3) | 6 |
| `GET /v1/conversations/counts` | 6 |
| `GET /v1/conversations/{id}`, `/messages`, `/notes`, `/assign`, `/status`, `/read`, `POST /v1/messages/{id}/retry` | 7 |
| `Message` with every WhatsApp type, signed media ([06](../06-api-contract.md) §3, [08](../08-screens.md) §3) | 7, 8 |
| `GET /v1/notifications`, `POST /v1/notifications/read` | 4 |
| `GET /v1/stream` and the live-update contract ([01](../01-architecture.md) §2 B, [06](../06-api-contract.md) §9) | 1, 9 |
| Assignment engine, round-robin under lock ([05](../05-workflows.md) §5) | 3 |
| Business hours and response targets, due-soon and missed | 2, 5 |
| `conversation_reads`, `notifications` and their policies ([02](../02-data-model.md) §2, §4) | 1 |
| Live-update triggers and `app.suppress_rt` ([02](../02-data-model.md) §5) | 1 |
| Inbox indexes and the `simple` full-text index ([02](../02-data-model.md) §6) | 1 |
| Inbox list, thread and composer screens ([08](../08-screens.md) §2–§4) | 11, 12, 13 |
| Live updates in the browser, invalidation not mutation ([07](../07-frontend.md) §3) | 10 |
| "A salesperson answers a customer end to end while the manager watches the timer" ([09](../09-implementation-plan.md)) | 14 |

## Execution

Task by task on `sales/phase-1`, with `superpowers:subagent-driven-development` or
`superpowers:executing-plans`. Suggested checkpoints: after 5 (the worker side), after 9 (the API
complete, provable with curl), after 14 (the slice). Every task ends with a green suite and one
commit — and Task 14 ends with a browser, not a test run.
