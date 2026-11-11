"""The queue: what each role sees, in what order, and what the counts say."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest
from fastapi.testclient import TestClient

from conftest import MANAGER, OWNER, SALES_1, SALES_2, TEAM_LOCAL, TENANT_A, reseed_with_people
from dealerai.config import get_settings
from dealerai.core.security import mint_test_token
from dealerai.main import app
from dealerai.routes.inbox import _preview

SECRET = "super-secret-jwt-token-with-at-least-32-characters-long"
CHANNEL = uuid.UUID("cccccccc-6666-4666-8666-000000000001")
NOW = datetime.now(UTC)

#: What the fixture builds, so a failure reads as a sentence.
WAITING_LONGEST = "Karim Benali"  # assigned to SALES_1, 40 minutes, target missed
WAITING_BRIEFLY = "Nadia Haddad"  # unassigned in the Local team, 5 minutes
ANSWERED = "James Whitfield"  # assigned to SALES_2, nobody waiting
CLOSED = "Mona Fathy"  # closed, assigned to SALES_1
VOICE = "Omar Al Mazrouei"  # assigned to SALES_1, a voice note with a transcript


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "supabase_jwt_secret", SECRET)


def _auth(user_id: uuid.UUID, tenant_id: uuid.UUID = TENANT_A) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {mint_test_token(user_id, secret=SECRET)}",
        "X-Tenant-Id": str(tenant_id),
    }


async def _conversation(
    conn: asyncpg.Connection,
    name: str,
    *,
    assigned_to: uuid.UUID | None,
    waiting_minutes: int | None = None,
    overdue: bool = False,
    status: str = "open",
    phone: str | None = None,
) -> uuid.UUID:
    contact_id = await conn.fetchval(
        """insert into contacts (tenant_id, full_name, country, locale, owner_id, team_id)
           values ($1, $2, 'AE', 'en', $3, $4) returning id""",
        TENANT_A,
        name,
        assigned_to,
        TEAM_LOCAL,
    )
    if phone:
        await conn.execute(
            """insert into contact_identities (tenant_id, contact_id, kind, value, is_primary)
               values ($1, $2, 'phone', $3, true)""",
            TENANT_A,
            contact_id,
            phone,
        )
    waiting_since = NOW - timedelta(minutes=waiting_minutes) if waiting_minutes else None
    due_at = None
    if waiting_since is not None:
        due_at = waiting_since + timedelta(minutes=5 if overdue else 120)
    return await conn.fetchval(  # type: ignore[no-any-return]
        """insert into conversations
             (tenant_id, contact_id, channel_id, surface, status, team_id, assigned_to, owner_id,
              waiting_since, sla_due_at, last_message_at, wa_window_expires_at)
           values ($1, $2, $3, 'whatsapp', $4, $5, $6, $6, $7, $8, coalesce($7, now()),
                   now() + interval '20 hours')
           returning id""",
        TENANT_A,
        contact_id,
        CHANNEL,
        status,
        TEAM_LOCAL,
        assigned_to,
        waiting_since,
        due_at,
    )


async def _message(
    conn: asyncpg.Connection,
    conversation_id: uuid.UUID,
    *,
    body: str | None = "Is it available?",
    direction: str = "in",
    transcript: str | None = None,
    minutes_ago: int = 1,
) -> uuid.UUID:
    return await conn.fetchval(  # type: ignore[no-any-return]
        """insert into messages (tenant_id, conversation_id, direction, sender, origin, type,
                                 body, transcript, created_at)
           values ($1, $2, $3, case when $3 = 'in' then 'customer' else 'human' end,
                   case when $3 = 'in' then 'customer' else 'inbox' end,
                   case when $5::text is null then 'text' else 'audio' end,
                   $4, case when $5::text is null then null
                            else jsonb_build_object('text', $5::text, 'language', 'en') end,
                   now() - make_interval(mins => $6))
           returning id""",
        TENANT_A,
        conversation_id,
        direction,
        body,
        transcript,
        minutes_ago,
    )


async def _seed_queue() -> None:
    await reseed_with_people()
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        await conn.execute(
            """insert into channels (id, tenant_id, platform, external_id, account_id, mode,
                                     display_name)
               values ($1, $2, 'whatsapp', 'queue-phone', 'queue-waba', 'coexistence', 'Pollux')""",
            CHANNEL,
            TENANT_A,
        )
        longest = await _conversation(
            conn, WAITING_LONGEST, assigned_to=SALES_1, waiting_minutes=40, overdue=True
        )
        await _message(conn, longest, minutes_ago=40)
        await _message(conn, longest, body="Still there?", minutes_ago=35)

        briefly = await _conversation(conn, WAITING_BRIEFLY, assigned_to=None, waiting_minutes=5)
        await _message(conn, briefly, minutes_ago=5)

        answered = await _conversation(conn, ANSWERED, assigned_to=SALES_2)
        await _message(conn, answered, body="Thanks!", direction="out", minutes_ago=10)

        closed = await _conversation(conn, CLOSED, assigned_to=SALES_1, status="closed")
        await _message(conn, closed, body="Sold, thank you", minutes_ago=600)

        voice = await _conversation(
            conn, VOICE, assigned_to=SALES_1, phone="+971500000101", waiting_minutes=20
        )
        await _message(
            conn,
            voice,
            body=None,
            transcript="is the land cruiser still available",
            minutes_ago=20,
        )
    finally:
        await conn.close()


@pytest.fixture
def client(_migrated: None) -> Iterator[TestClient]:
    asyncio.run(_seed_queue())
    with TestClient(app) as test_client:
        yield test_client


def _rows(client: TestClient, user: uuid.UUID, query: str = "view=mine") -> list[dict[str, object]]:
    response = client.get(f"/v1/conversations?{query}", headers=_auth(user))
    assert response.status_code == 200, response.text
    return response.json()["data"]  # type: ignore[no-any-return]


def _names(rows: list[dict[str, object]]) -> list[str]:
    return [row["contact"]["name"] for row in rows]  # type: ignore[index]


def test_mine_holds_only_my_conversations(client: TestClient) -> None:
    assert set(_names(_rows(client, SALES_1))) == {WAITING_LONGEST, VOICE}


def test_waiting_customers_come_first_oldest_first(client: TestClient) -> None:
    rows = _rows(client, OWNER, "view=all")
    waiting = [row["waiting_since"] for row in rows if row["waiting_since"]]
    assert waiting == sorted(waiting), "the customer waiting longest is not at the top"
    assert _names(rows)[:3] == [WAITING_LONGEST, VOICE, WAITING_BRIEFLY]
    assert all(row["waiting_since"] is None for row in rows[3:]), "nobody waiting sorts last"
    assert ANSWERED in _names(rows[3:])


def test_a_salesperson_is_offered_only_the_views_that_mean_something(client: TestClient) -> None:
    """Their `team` and `all` would show exactly their own rows, because RLS
    already filtered them. Saying so is clearer than an identical list."""
    for view in ("team", "all"):
        assert (
            client.get(f"/v1/conversations?view={view}", headers=_auth(SALES_1)).status_code == 403
        )
    assert set(_names(_rows(client, SALES_1, "view=mine"))) == {WAITING_LONGEST, VOICE}


def test_the_team_view_needs_a_manager(client: TestClient) -> None:
    assert client.get("/v1/conversations?view=team", headers=_auth(SALES_1)).status_code == 403
    assert client.get("/v1/conversations?view=team", headers=_auth(MANAGER)).status_code == 200


def test_the_unassigned_queue_is_what_nobody_owns(client: TestClient) -> None:
    assert _names(_rows(client, MANAGER, "view=unassigned")) == [WAITING_BRIEFLY]


def test_a_closed_conversation_is_not_in_the_open_queue(client: TestClient) -> None:
    assert CLOSED not in _names(_rows(client, SALES_1, "view=mine"))
    assert CLOSED in _names(_rows(client, SALES_1, "view=mine&status=closed"))


def test_unread_counts_what_i_have_not_read(client: TestClient) -> None:
    rows = _rows(client, SALES_1)
    longest = next(row for row in rows if row["contact"]["name"] == WAITING_LONGEST)  # type: ignore[index]
    assert longest["unread_count"] == 2

    asyncio.run(_read_now(uuid.UUID(str(longest["id"])), SALES_1))
    after = _rows(client, SALES_1)
    assert (
        next(
            row
            for row in after
            if row["contact"]["name"] == WAITING_LONGEST  # type: ignore[index]
        )["unread_count"]
        == 0
    )


async def _read_now(conversation_id: uuid.UUID, user_id: uuid.UUID) -> None:
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        await conn.execute(
            """insert into conversation_reads (tenant_id, conversation_id, user_id, last_read_at)
               values ($1, $2, $3, now())""",
            TENANT_A,
            conversation_id,
            user_id,
        )
    finally:
        await conn.close()


def test_the_timer_says_how_late_we_are(client: TestClient) -> None:
    rows = _rows(client, OWNER, "view=all")
    states = {row["contact"]["name"]: row["sla_state"] for row in rows}  # type: ignore[index]
    assert states[WAITING_LONGEST] == "breached"
    assert states[WAITING_BRIEFLY] == "ok"
    assert states[ANSWERED] is None, "a conversation nobody waits on has no state"


def test_the_row_carries_what_the_screen_draws(client: TestClient) -> None:
    [row] = [r for r in _rows(client, OWNER, "view=all") if r["contact"]["name"] == VOICE]  # type: ignore[index]
    assert row["channel"]["platform"] == "whatsapp"  # type: ignore[index]
    assert row["team"]["id"] == str(TEAM_LOCAL)  # type: ignore[index]
    assert row["assignee"]["id"] == str(SALES_1)  # type: ignore[index]
    assert row["window_expires_at"] is not None
    assert row["has_ai_draft"] is False
    # A voice note has no body, so the preview says what arrived.
    assert row["last_message"]["type"] == "audio"  # type: ignore[index]
    assert "land cruiser" in str(row["last_message"]["preview"])  # type: ignore[index]


def test_a_photo_with_no_caption_has_no_words() -> None:
    """What kind of thing arrived is the screen's to say, in its reader's language."""
    assert _preview({"body": None, "transcript": None, "last_type": "image"}) == ""
    assert _preview({"body": "The white one", "transcript": None, "last_type": "image"}) == (
        "The white one"
    )


def test_search_finds_a_voice_note_by_what_was_said(client: TestClient) -> None:
    assert _names(_rows(client, OWNER, "view=all&q=land%20cruiser")) == [VOICE]


def test_search_finds_a_customer_by_number_or_name(client: TestClient) -> None:
    assert _names(_rows(client, OWNER, "view=all&q=500000101")) == [VOICE]
    assert _names(_rows(client, OWNER, "view=all&q=nadia")) == [WAITING_BRIEFLY]


def test_counts_cover_every_view_the_caller_may_open(client: TestClient) -> None:
    counts = client.get("/v1/conversations/counts", headers=_auth(MANAGER)).json()
    assert set(counts) == {"mine", "unassigned", "team"}
    assert counts["unassigned"]["waiting"] == 1
    assert counts["team"]["waiting"] == 3
    sales = client.get("/v1/conversations/counts", headers=_auth(SALES_1)).json()
    assert set(sales) == {"mine", "unassigned"}
    assert sales["mine"]["unread"] == 3


def test_the_page_walks_forward_without_repeating(client: TestClient) -> None:
    first = client.get("/v1/conversations?view=all&limit=2", headers=_auth(OWNER)).json()
    assert len(first["data"]) == 2 and first["next_cursor"]
    second = client.get(
        f"/v1/conversations?view=all&limit=2&cursor={first['next_cursor']}", headers=_auth(OWNER)
    ).json()
    assert {row["id"] for row in first["data"]}.isdisjoint({row["id"] for row in second["data"]})
    assert _names(first["data"] + second["data"])[:3] == [WAITING_LONGEST, VOICE, WAITING_BRIEFLY]


def test_a_cursor_from_somewhere_else_is_refused(client: TestClient) -> None:
    response = client.get("/v1/conversations?view=all&cursor=not-ours", headers=_auth(OWNER))
    assert response.status_code == 422
