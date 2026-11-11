"""A notification is written in the language its reader reads (S7 Part C).

It is written when its reader is not there to ask, so the language is the one
the browser last said (`profiles.locale`). Both sentences are given where the
thing is told; which one is kept is decided on insert, for the row's own reader.
"""

from __future__ import annotations

import ast
import json
import uuid
from pathlib import Path

import asyncpg

import dealerai
from conftest import (
    MANAGER,
    PHONE,
    SALES_1,
    SALES_2,
    TENANT_A,
    USER_A,
    PushService,
    open_push,
    reseed_with_people,
)
from dealerai.core.words import Words, named, same, someone
from dealerai.db.session import tenant_session
from dealerai.events.bus import Event
from dealerai.events.handlers import crm, inbox
from dealerai.events.handlers import notify as notifications

CONVERSATION = "11111111-1111-4111-8111-111111111111"
WAITING = Words("A customer is waiting for you", "عميل بانتظارك")


async def _reads_arabic(su: asyncpg.Connection, user: uuid.UUID) -> None:
    await su.execute("update profiles set locale = 'ar' where id = $1", user)


async def _tell(user: uuid.UUID, body: Words | None = None) -> None:
    """What a handler does when somebody should know, in the worker's session."""
    async with tenant_session(TENANT_A) as conn:
        await notifications.notify(
            conn,
            tenant_id=TENANT_A,
            user_id=user,
            kind="assigned",
            title=WAITING,
            body=body,
            entity={"type": "conversation", "id": CONVERSATION},
            dedupe_key=f"told:{user}",
        )


async def _told(su: asyncpg.Connection, user: uuid.UUID) -> asyncpg.Record:
    return await su.fetchrow(  # type: ignore[no-any-return]
        "select title, body from notifications where user_id = $1", user
    )


async def test_an_arabic_reader_is_told_in_arabic(db: None, su: asyncpg.Connection) -> None:
    await reseed_with_people()
    await _reads_arabic(su, SALES_1)

    for user in (SALES_1, SALES_2):
        await _tell(user, body=same("Omar Haddad"))

    assert tuple(await _told(su, SALES_1)) == ("عميل بانتظارك", "Omar Haddad")
    assert tuple(await _told(su, SALES_2)) == ("A customer is waiting for you", "Omar Haddad")


async def test_somebody_who_never_said_is_told_in_english(db: None, su: asyncpg.Connection) -> None:
    """An owner from before profiles were written has a membership and no row."""
    await reseed_with_people()
    assert await su.fetchval("select 1 from profiles where id = $1", USER_A) is None

    await _tell(USER_A)

    assert (await _told(su, USER_A))["title"] == "A customer is waiting for you"


async def test_the_push_carries_the_same_words(
    db: None, su: asyncpg.Connection, push_service: PushService
) -> None:
    await reseed_with_people()
    await _reads_arabic(su, SALES_1)
    await su.execute(
        """insert into push_subscriptions (tenant_id, user_id, endpoint, p256dh, auth)
           values ($1, $2, $3, $4, $5)""",
        TENANT_A,
        SALES_1,
        PHONE["endpoint"],
        PHONE["p256dh"],
        PHONE["auth"],
    )

    await _tell(SALES_1)
    row = await su.fetchrow(
        """select id, tenant_id, event_type, payload, dedupe_key from events
            where event_type = 'notification.push_requested'"""
    )
    await notifications.on_push_requested(
        Event(row["id"], row["tenant_id"], row["event_type"], json.loads(row["payload"]), 1, None)
    )

    [request] = push_service.requests
    assert open_push(request.content)["title"] == "عميل بانتظارك"


async def test_a_name_stays_a_name(db: None, su: asyncpg.Connection) -> None:
    """The sentence is the reader's; the customer and the colleague are who they are."""
    await reseed_with_people()
    await _reads_arabic(su, SALES_1)
    contact = await su.fetchval(
        "insert into contacts (tenant_id, full_name) values ($1, 'Omar Al Mazrouei') returning id",
        TENANT_A,
    )

    await crm.on_contact_reassigned(
        Event(
            1,
            TENANT_A,
            "contact.reassigned",
            {"contact_id": str(contact), "owner_id": str(SALES_1), "actor_id": str(MANAGER)},
            1,
            None,
        )
    )

    told = await _told(su, SALES_1)
    assert told["title"] == f"{named('Omar Al Mazrouei')} أصبح من عملائك"
    assert told["body"] == f"سلّمه إليك {named('manager')}"


def test_a_name_is_kept_apart_from_the_direction_of_its_sentence() -> None:
    """FIRST STRONG ISOLATE … POP DIRECTIONAL ISOLATE. Without them a Latin name
    at the start of an Arabic sentence turns the whole line left to right, in the
    bell and on a phone's lock screen — and an Arabic name does the same to an
    English one. The bell reads them with `unicode-bidi: plaintext`."""
    assert named("Omar") == "\u2068Omar\u2069"
    assert someone("Omar") == Words("\u2068Omar\u2069", "\u2068Omar\u2069")
    assert someone(None) == Words("A customer", "أحد العملاء")


def test_every_fixed_sentence_is_in_both_languages() -> None:
    for kind, (title, body) in inbox._NOTIFICATIONS.items():
        for said in (title, body):
            if said is None:
                continue
            assert said.en != said.ar and _is_arabic(said.ar), kind


# --------------------------------------------------------------------------
# the contract
# --------------------------------------------------------------------------

SRC = Path(dealerai.__file__).parent


def _is_arabic(text: str) -> bool:
    return any("؀" <= char <= "ۿ" for char in text)


def _literal(node: ast.expr) -> str | None:
    """The written part of a string or an f-string; None for anything else."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            part.value
            for part in node.values
            if isinstance(part, ast.Constant) and isinstance(part.value, str)
        )
    return None


def _calls(name: str) -> list[tuple[str, ast.Call]]:
    found = []
    for path in sorted(SRC.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            called = node.func
            if (isinstance(called, ast.Name) and called.id == name) or (
                isinstance(called, ast.Attribute) and called.attr == name
            ):
                found.append((f"{path.relative_to(SRC)}:{node.lineno}", node))
    return found


def test_every_notification_has_both() -> None:
    """Nobody is told anything in one language only: what `notify()` is given is
    `Words`, and a bare sentence where they belong is a sentence in English."""
    told = _calls("notify")
    assert len(told) >= 9, "the scan lost the call sites it is here to watch"
    bare = [
        f"{where} {keyword.arg}="
        for where, call in told
        for keyword in call.keywords
        if keyword.arg in ("title", "body") and _literal(keyword.value) is not None
    ]
    assert not bare, f"said in one language only: {bare}"


def test_words_are_two_sentences_and_data_is_same() -> None:
    """`Words(en, ar)` is a sentence in each language. One thing given twice —
    a name, a title somebody typed — is `same()`, which says so."""
    wrong = []
    for where, call in _calls("Words"):
        # same() itself is the one place that gives one thing twice.
        if len(call.args) != 2 or Path(where.split(":")[0]).name == "words.py":
            continue
        english, arabic = call.args
        written = _literal(arabic)
        if written is not None and not _is_arabic(written):
            wrong.append(f"{where}: the second sentence is not Arabic")
        if written is None and ast.dump(english) == ast.dump(arabic):
            wrong.append(f"{where}: the same thing twice is same()")
    assert not wrong, wrong
