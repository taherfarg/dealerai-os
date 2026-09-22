"""The draft over HTTP, and what became of it.

The outcome is the number this slice is judged on, so most of these are about
it being recorded exactly once, with the message, and never twice.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg
import pytest
from fastapi.testclient import TestClient

from conftest import MANAGER, SALES_1, SALES_2, TEAM_LOCAL, TENANT_A, reseed_with_people
from dealerai.config import get_settings
from dealerai.core.security import mint_test_token
from dealerai.main import app
from dealerai.routes.suggestions import edit_ratio

SECRET = "super-secret-jwt-token-with-at-least-32-characters-long"
DRAFT = "Yes, the Land Cruiser 2023 is available at AED 235,000. Saturday at 11:00?"


@pytest.fixture(autouse=True)
def _jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "supabase_jwt_secret", SECRET)


def _auth(user_id: uuid.UUID) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {mint_test_token(user_id, secret=SECRET)}",
        "X-Tenant-Id": str(TENANT_A),
    }


def _key() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid.uuid4())}


async def _build(owner: uuid.UUID = SALES_1, *, status: str = "ready") -> dict[str, Any]:
    """One conversation owned by `owner`, with a draft waiting on it."""
    await reseed_with_people()
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        channel_id = await conn.fetchval(
            """insert into channels (tenant_id, platform, external_id, handle, status)
               values ($1, 'whatsapp', $2, '+971 4 123 4567', 'connected') returning id""",
            TENANT_A,
            f"wa-{uuid.uuid4()}",
        )
        contact_id = await conn.fetchval(
            """insert into contacts (tenant_id, full_name, owner_id, team_id)
               values ($1, 'Omar Al Mazrouei', $2, $3) returning id""",
            TENANT_A,
            owner,
            TEAM_LOCAL,
        )
        conversation_id = await conn.fetchval(
            """insert into conversations
                 (tenant_id, contact_id, channel_id, surface, status, owner_id, assigned_to,
                  wa_window_expires_at)
               values ($1,$2,$3,'whatsapp','open',$4,$4,$5) returning id""",
            TENANT_A,
            contact_id,
            channel_id,
            owner,
            datetime.now(UTC) + timedelta(hours=10),
        )
        message_id = await conn.fetchval(
            """insert into messages (tenant_id, conversation_id, kind, direction, sender, origin,
                                     type, body)
               values ($1,$2,'message','in','customer','customer','text','how much?')
               returning id""",
            TENANT_A,
            conversation_id,
        )
        suggestion_id = await conn.fetchval(
            """insert into ai_suggestions
                 (tenant_id, conversation_id, for_message_id, status, text, language, confidence,
                  intent, blocked_reason)
               values ($1,$2,$3,$4,$5,'en','high','price',$6) returning id""",
            TENANT_A,
            conversation_id,
            message_id,
            status,
            DRAFT if status != "blocked" else None,
            "it quoted a price that is not ours" if status == "blocked" else None,
        )
        return {
            "conversation": uuid.UUID(str(conversation_id)),
            "suggestion": uuid.UUID(str(suggestion_id)),
            "message": uuid.UUID(str(message_id)),
            "contact": uuid.UUID(str(contact_id)),
        }
    finally:
        await conn.close()


async def _suggestion(suggestion_id: uuid.UUID) -> asyncpg.Record:
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        row = await conn.fetchrow(
            """select status, outcome, edit_ratio, discard_reason, final_message_id, outcome_by
                 from ai_suggestions where id = $1""",
            suggestion_id,
        )
        assert row is not None
        return row
    finally:
        await conn.close()


async def _events(event_type: str) -> list[asyncpg.Record]:
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        return await conn.fetch(  # type: ignore[no-any-return]
            "select payload from events where event_type = $1 and tenant_id = $2",
            event_type,
            TENANT_A,
        )
    finally:
        await conn.close()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


# ---------------------------------------------------------------------------
# Reading it
# ---------------------------------------------------------------------------


def test_a_salesperson_sees_the_draft_on_their_own_conversation(client: TestClient) -> None:
    built = asyncio.run(_build())
    body = client.get(
        f"/v1/conversations/{built['conversation']}/suggestion", headers=_auth(SALES_1)
    ).json()
    assert body["text"] == DRAFT
    assert body["confidence"] == "high"
    assert body["intent"] == "price"


def test_a_draft_on_a_colleagues_conversation_is_not_there(client: TestClient) -> None:
    """Cross-visibility is never a 403: a 403 confirms the conversation exists."""
    built = asyncio.run(_build(owner=SALES_2))
    response = client.get(
        f"/v1/conversations/{built['conversation']}/suggestion", headers=_auth(SALES_1)
    )
    assert response.status_code == 200
    assert response.json() is None


def test_a_manager_sees_their_teams_drafts(client: TestClient) -> None:
    built = asyncio.run(_build(owner=SALES_1))
    body = client.get(
        f"/v1/conversations/{built['conversation']}/suggestion", headers=_auth(MANAGER)
    ).json()
    assert body is not None and body["text"] == DRAFT


def test_a_blocked_draft_is_returned_with_its_reason(client: TestClient) -> None:
    """The composer shows one muted line. Hiding it makes the AI look broken."""
    built = asyncio.run(_build(status="blocked"))
    body = client.get(
        f"/v1/conversations/{built['conversation']}/suggestion", headers=_auth(SALES_1)
    ).json()
    assert body["status"] == "blocked"
    assert body["blocked_reason"] == "it quoted a price that is not ours"
    assert body["text"] is None


def test_a_superseded_draft_is_not_returned(client: TestClient) -> None:
    built = asyncio.run(_build(status="superseded"))
    response = client.get(
        f"/v1/conversations/{built['conversation']}/suggestion", headers=_auth(SALES_1)
    )
    assert response.json() is None


def test_a_conversation_with_no_draft_answers_null(client: TestClient) -> None:
    asyncio.run(reseed_with_people())
    response = client.get(f"/v1/conversations/{uuid.uuid4()}/suggestion", headers=_auth(SALES_1))
    assert response.status_code == 200 and response.json() is None


def test_the_inbox_row_says_a_draft_is_waiting(client: TestClient) -> None:
    built = asyncio.run(_build())
    rows = client.get("/v1/conversations?view=mine", headers=_auth(SALES_1)).json()["data"]
    row = next(r for r in rows if r["id"] == str(built["conversation"]))
    assert row["has_ai_draft"] is True


def test_the_inbox_row_stops_saying_so_once_the_draft_is_used(client: TestClient) -> None:
    built = asyncio.run(_build())
    client.post(
        f"/v1/suggestions/{built['suggestion']}/outcome",
        json={"outcome": "discarded", "reason": "not_needed"},
        headers=_auth(SALES_1),
    )
    rows = client.get("/v1/conversations?view=mine", headers=_auth(SALES_1)).json()["data"]
    row = next(r for r in rows if r["id"] == str(built["conversation"]))
    assert row["has_ai_draft"] is False


# ---------------------------------------------------------------------------
# Sending it
# ---------------------------------------------------------------------------


def test_sending_a_draft_unchanged_records_it_as_sent(client: TestClient) -> None:
    built = asyncio.run(_build())
    response = client.post(
        f"/v1/conversations/{built['conversation']}/messages",
        json={"text": DRAFT, "suggestion_id": str(built["suggestion"])},
        headers={**_auth(SALES_1), **_key()},
    )
    assert response.status_code == 202

    row = asyncio.run(_suggestion(built["suggestion"]))
    assert row["outcome"] == "sent"
    assert float(row["edit_ratio"]) == 0.0
    assert str(row["final_message_id"]) == response.json()["id"]
    assert row["outcome_by"] == SALES_1
    assert row["status"] == "superseded"  # no longer the live draft


def test_fixing_a_name_still_counts_as_accepted(client: TestClient) -> None:
    """edit_ratio <= 0.2 is "lightly edited". If this drifts, the headline
    acceptance number moves without anything failing."""
    built = asyncio.run(_build())
    sent = DRAFT.replace("Yes,", "Yes Ahmed,")
    client.post(
        f"/v1/conversations/{built['conversation']}/messages",
        json={"text": sent, "suggestion_id": str(built["suggestion"])},
        headers={**_auth(SALES_1), **_key()},
    )
    row = asyncio.run(_suggestion(built["suggestion"]))
    assert row["outcome"] == "edited"
    assert 0 < float(row["edit_ratio"]) <= 0.2


def test_rewriting_it_completely_is_recorded_as_such(client: TestClient) -> None:
    built = asyncio.run(_build())
    client.post(
        f"/v1/conversations/{built['conversation']}/messages",
        json={
            "text": "Call me on Saturday and we will talk about the Prado instead.",
            "suggestion_id": str(built["suggestion"]),
        },
        headers={**_auth(SALES_1), **_key()},
    )
    row = asyncio.run(_suggestion(built["suggestion"]))
    assert row["outcome"] == "edited" and float(row["edit_ratio"]) > 0.2


def test_sending_without_a_draft_records_nothing(client: TestClient) -> None:
    built = asyncio.run(_build())
    client.post(
        f"/v1/conversations/{built['conversation']}/messages",
        json={"text": "Typed from scratch."},
        headers={**_auth(SALES_1), **_key()},
    )
    assert asyncio.run(_suggestion(built["suggestion"]))["outcome"] is None


def test_sending_with_another_conversations_suggestion_still_sends(client: TestClient) -> None:
    """The message is already written. Refusing it would lose a real reply to a
    bookkeeping mistake."""
    built = asyncio.run(_build())
    response = client.post(
        f"/v1/conversations/{built['conversation']}/messages",
        json={"text": "Hello.", "suggestion_id": str(uuid.uuid4())},
        headers={**_auth(SALES_1), **_key()},
    )
    assert response.status_code == 202
    assert asyncio.run(_suggestion(built["suggestion"]))["outcome"] is None


def test_a_send_that_fails_records_no_outcome(client: TestClient) -> None:
    """One transaction: an outcome written for a message that never existed
    would inflate the metric by exactly the failures."""
    built = asyncio.run(_build())
    conn_error = client.post(
        f"/v1/conversations/{built['conversation']}/messages",
        json={"template_id": str(uuid.uuid4()), "suggestion_id": str(built["suggestion"])},
        headers={**_auth(SALES_1), **_key()},
    )
    assert conn_error.status_code == 404
    assert asyncio.run(_suggestion(built["suggestion"]))["outcome"] is None


def test_a_retried_send_does_not_record_a_second_outcome(client: TestClient) -> None:
    """The idempotency key returns the first message; the draft was already
    accounted for."""
    built = asyncio.run(_build())
    headers = {**_auth(SALES_1), **_key()}
    body = {"text": DRAFT, "suggestion_id": str(built["suggestion"])}
    first = client.post(
        f"/v1/conversations/{built['conversation']}/messages", json=body, headers=headers
    )
    second = client.post(
        f"/v1/conversations/{built['conversation']}/messages", json=body, headers=headers
    )
    assert first.json()["id"] == second.json()["id"]
    assert asyncio.run(_suggestion(built["suggestion"]))["outcome"] == "sent"


# ---------------------------------------------------------------------------
# Dismissing it
# ---------------------------------------------------------------------------


def test_dismissing_records_the_reason(client: TestClient) -> None:
    built = asyncio.run(_build())
    response = client.post(
        f"/v1/suggestions/{built['suggestion']}/outcome",
        json={"outcome": "discarded", "reason": "wrong_info"},
        headers=_auth(SALES_1),
    )
    assert response.status_code == 204
    row = asyncio.run(_suggestion(built["suggestion"]))
    assert (row["outcome"], row["discard_reason"]) == ("discarded", "wrong_info")


def test_a_discard_needs_one_of_the_four_reasons(client: TestClient) -> None:
    """Free text would be unreadable in aggregate, and reading it in aggregate
    is the whole point of collecting it."""
    built = asyncio.run(_build())
    response = client.post(
        f"/v1/suggestions/{built['suggestion']}/outcome",
        json={"outcome": "discarded", "reason": "because I said so"},
        headers=_auth(SALES_1),
    )
    assert response.status_code == 422


def test_an_outcome_cannot_be_recorded_twice(client: TestClient) -> None:
    """Otherwise a dismissed draft could be re-scored as sent, which moves the
    acceptance metric after the fact."""
    built = asyncio.run(_build())
    for outcome in ("discarded", "sent"):
        client.post(
            f"/v1/suggestions/{built['suggestion']}/outcome",
            json={"outcome": outcome, "reason": "not_needed" if outcome == "discarded" else None},
            headers=_auth(SALES_1),
        )
    assert asyncio.run(_suggestion(built["suggestion"]))["outcome"] == "discarded"


def test_a_suggestion_that_is_not_there_is_a_404(client: TestClient) -> None:
    asyncio.run(reseed_with_people())
    response = client.post(
        f"/v1/suggestions/{uuid.uuid4()}/outcome",
        json={"outcome": "discarded"},
        headers=_auth(SALES_1),
    )
    assert response.status_code == 404


def test_a_colleagues_draft_cannot_be_dismissed(client: TestClient) -> None:
    built = asyncio.run(_build(owner=SALES_2))
    response = client.post(
        f"/v1/suggestions/{built['suggestion']}/outcome",
        json={"outcome": "discarded", "reason": "not_needed"},
        headers=_auth(SALES_1),
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Asking for another
# ---------------------------------------------------------------------------


def test_regenerating_queues_a_forced_run(client: TestClient) -> None:
    built = asyncio.run(_build())
    response = client.post(
        f"/v1/conversations/{built['conversation']}/suggestion/regenerate",
        headers=_auth(SALES_1),
    )
    assert response.status_code == 202
    queued = asyncio.run(_events("copilot.draft_requested"))
    assert len(queued) == 1
    import json

    assert json.loads(queued[0]["payload"])["forced"] is True


def test_regenerating_twice_in_a_minute_queues_one_run(client: TestClient) -> None:
    """A salesperson mashing the button should not queue five model calls."""
    built = asyncio.run(_build())
    for _ in range(3):
        client.post(
            f"/v1/conversations/{built['conversation']}/suggestion/regenerate",
            headers=_auth(SALES_1),
        )
    assert len(asyncio.run(_events("copilot.draft_requested"))) == 1


def test_the_live_draft_survives_until_the_new_one_claims_it(client: TestClient) -> None:
    """A worker that dies must not leave the salesperson looking at nothing."""
    built = asyncio.run(_build())
    client.post(
        f"/v1/conversations/{built['conversation']}/suggestion/regenerate",
        headers=_auth(SALES_1),
    )
    body = client.get(
        f"/v1/conversations/{built['conversation']}/suggestion", headers=_auth(SALES_1)
    ).json()
    assert body["text"] == DRAFT


def test_regenerating_a_conversation_the_customer_has_not_written_in_is_refused(
    client: TestClient,
) -> None:
    asyncio.run(reseed_with_people())
    response = client.post(
        f"/v1/conversations/{uuid.uuid4()}/suggestion/regenerate", headers=_auth(SALES_1)
    )
    assert response.status_code == 422


def test_somebody_who_cannot_send_cannot_ask_for_another_draft(client: TestClient) -> None:
    """Regenerating spends the dealership's money, so it needs inbox.send."""
    built = asyncio.run(_build())
    viewer = uuid.uuid4()
    asyncio.run(_add_a_viewer(viewer))
    try:
        response = client.post(
            f"/v1/conversations/{built['conversation']}/suggestion/regenerate",
            headers=_auth(viewer),
        )
        assert response.status_code == 403
    finally:
        asyncio.run(_remove(viewer))


async def _add_a_viewer(user_id: uuid.UUID) -> None:
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        # Unique per run: _wipe only knows the fixed people, so a stray row
        # here would fail the next run on the email's unique index.
        await conn.execute(
            "insert into auth.users (id, email) values ($1, $2)",
            user_id,
            f"viewer-{user_id}@example.test",
        )
        await conn.execute(
            "insert into memberships (tenant_id, user_id, role) values ($1, $2, 'viewer')",
            TENANT_A,
            user_id,
        )
    finally:
        await conn.close()


async def _remove(user_id: uuid.UUID) -> None:
    conn = await asyncpg.connect(get_settings().migration_dsn)
    try:
        await conn.execute("delete from auth.users where id = $1", user_id)
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# The arithmetic
# ---------------------------------------------------------------------------


def test_an_unchanged_reply_is_zero() -> None:
    assert edit_ratio(DRAFT, DRAFT) == 0.0


def test_a_draft_that_was_never_written_has_no_ratio() -> None:
    """A blocked draft has no text, so nothing was edited."""
    assert edit_ratio(None, "anything") is None


def test_a_template_send_has_no_ratio() -> None:
    assert edit_ratio(DRAFT, None) is None
