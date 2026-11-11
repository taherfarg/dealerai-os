"""A refusal is said in the language of whoever it refuses (S7 Part C).

The browser sends the language on screen as `Accept-Language`. The sentence in
each language sits at the raise site — `ar=` beside the English — so whoever
changes the one sees the other. The last test here is the contract that keeps
it that way.
"""

from __future__ import annotations

import ast
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

import dealerai
from dealerai.core.errors import AppError, Conflict, NotFound, install_error_handlers

ARABIC = {"Accept-Language": "ar"}


class _Form(BaseModel):
    count: int


def _client() -> TestClient:
    """The error handlers on their own: nothing here needs a database."""
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/both")
    async def both() -> None:
        raise Conflict("that name is taken", ar="هذا الاسم مستخدم")

    @app.get("/english-only")
    async def english_only() -> None:
        raise Conflict("said in English so far")

    @app.get("/missing")
    async def missing() -> None:
        raise NotFound("no such thing")

    @app.post("/form")
    async def form(body: _Form) -> None:
        return None

    return TestClient(app)


def _detail(path: str, headers: dict[str, str] | None = None) -> str:
    return str(_client().get(path, headers=headers).json()["detail"])


def test_a_refusal_is_said_in_the_readers_language() -> None:
    assert _detail("/both", ARABIC) == "هذا الاسم مستخدم"
    assert _detail("/both") == "that name is taken", "nobody else's changed"
    assert _detail("/both", {"Accept-Language": "en-GB,en;q=0.9"}) == "that name is taken"


def test_what_the_browser_itself_prefers_is_not_what_is_on_screen() -> None:
    """The web app sends the UI's language alone. A browser's own list, with
    Arabic somewhere down it, is not somebody reading the app in Arabic."""
    assert _detail("/both", {"Accept-Language": "en-US,ar;q=0.8"}) == "that name is taken"
    assert _detail("/both", {"Accept-Language": "ar-AE,ar;q=0.9,en;q=0.8"}) == "هذا الاسم مستخدم"


def test_a_refusal_with_no_arabic_yet_is_still_said() -> None:
    assert _detail("/english-only", ARABIC) == "said in English so far"


def test_something_that_is_not_there_is_said_plainly() -> None:
    """ "no such thing" is for whoever is debugging. A person reading Arabic is
    told that it is gone, in a sentence that fits whatever it was."""
    said = _detail("/missing", ARABIC)
    assert said != "no such thing" and any("؀" <= char <= "ۿ" for char in said)
    assert _detail("/missing") == "no such thing"


def test_an_invalid_form_is_refused_in_arabic_too() -> None:
    client = _client()
    english = client.post("/form", json={"count": "many"})
    arabic = client.post("/form", json={"count": "many"}, headers=ARABIC)
    assert english.status_code == arabic.status_code == 400
    assert english.json()["detail"] == "One or more fields failed validation."
    assert arabic.json()["detail"] != english.json()["detail"]
    # Which field it was is for the form, in either language.
    assert (
        arabic.json()["errors"]
        == english.json()["errors"]
        == [{"field": "count", "code": "int_parsing"}]
    )


# --------------------------------------------------------------------------
# the contract
# --------------------------------------------------------------------------

SRC = Path(dealerai.__file__).parent

#: Where a person's click can end in a refusal: the Sales module's routes, the
#: permission checks every route shares, and what validates a customer's profile.
SCANNED = [
    *sorted((SRC / "routes").glob("*.py")),
    SRC / "deps.py",
    SRC / "sales" / "profile.py",
]

#: Whole modules a Sales screen never calls.
NOT_A_SALES_SCREEN = {
    "approvals.py": "DealerAI OS's Marketing screens, which Part C does not cover",
    "imports.py": "the inventory import, a Marketing screen",
    "vehicles.py": "inventory, a Marketing screen",
    "runs.py": "agent runs, a Marketing screen",
    "dev.py": "local sign-in; the route does not exist in production",
    "webhooks.py": "Meta is the caller, not a person",
}

#: Refusals with their own answer for an Arabic reader, or no reader at all.
EXEMPT_CLASSES = {
    "NotFound": "answered by the class's own Arabic sentence: whatever it was, it is gone",
    "PushUnavailable": "a missing server key — the screen has its own words for a 503",
    "AuthUnavailable": "a missing server secret, for whoever runs the server",
}

#: Sentences only a client that is wrong can cause. Matched on how they begin.
EXEMPT_SENTENCES = {
    "expected an Authorization: Bearer header": "a request with no session at all, not a person",
    "that cursor is not one of ours": "a cursor is the API's own, handed back unchanged",
    "kind is one of": "the upload form offers only the kinds there are",
    "reason is one of": "the dismiss buttons are the reasons there are",
    "that stage belongs to a different pipeline": "a board offers only its own stages",
    "one of those stages belongs to a different pipeline": "a board sends only its own stages",
    " is not something we record about a customer": "the profile shows only the fields there are",
    " must be an amount in minor units": "the budget field sends minor units itself",
    "purchase_type is local or export": "a select with those two choices",
    "payment is cash or finance": "a select with those two choices",
    " is a list": "the objections field sends a list itself",
}


def _refusals(path: Path) -> list[tuple[int, str, str, bool]]:
    """Every `raise SomeAppError(...)` in a file: line, class, how its sentence
    begins, and whether it says it in Arabic."""
    family = {cls.__name__ for cls in _descendants(AppError)}
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not (isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call)):
            continue
        call = node.exc
        name = call.func.id if isinstance(call.func, ast.Name) else ""
        if name not in family:
            continue
        found.append(
            (
                node.lineno,
                name,
                _beginning(call.args[0]) if call.args else "",
                any(keyword.arg == "ar" for keyword in call.keywords),
            )
        )
    return found


def _descendants(cls: type) -> set[type]:
    children = set(cls.__subclasses__())
    return children | {grand for child in children for grand in _descendants(child)}


def _beginning(node: ast.expr) -> str:
    """The literal a sentence starts with — all of a plain string, the part of
    an f-string before or after its first value."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return next(
            (
                part.value
                for part in node.values
                if isinstance(part, ast.Constant) and isinstance(part.value, str)
            ),
            "",
        )
    return ""


def test_every_refusal_a_screen_can_cause_has_arabic() -> None:
    import dealerai.main  # noqa: F401, PLC0415 — defines every error class the routes raise

    missing = []
    for path in SCANNED:
        if path.name in NOT_A_SALES_SCREEN:
            continue
        for line, name, begins, arabic in _refusals(path):
            if arabic or name in EXEMPT_CLASSES:
                continue
            if any(begins.startswith(sentence) for sentence in EXEMPT_SENTENCES):
                continue
            missing.append(f"{path.relative_to(SRC)}:{line}  {name}({begins!r}…)")
    assert not missing, (
        "a refusal a person can cause is said in English only — add ar=, or list it "
        "as exempt here with the reason:\n  " + "\n  ".join(missing)
    )


def test_the_exemptions_still_name_something() -> None:
    """An exemption for a sentence nobody raises any more is a hole in the net."""
    raised = [begins for path in SCANNED for _, _, begins, _ in _refusals(path)]
    stale = [
        sentence
        for sentence in EXEMPT_SENTENCES
        if not any(begins.startswith(sentence) for begins in raised)
    ]
    assert not stale, f"nothing raises these any more: {stale}"
