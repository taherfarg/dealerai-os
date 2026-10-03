"""`npm run smoke`: is a deployment fit to be used?

Against a stand-in that answers as a deployment does — an API, a web app and a
Supabase project — with one thing wrong at a time.
"""

from __future__ import annotations

import httpx
import pytest

from dealerai.scripts import smoke

API = "https://api.staging.example"
WEB = "https://app.staging.example"
PROJECT = "https://abcdefghijklmnop.supabase.co"
EVERYTHING = ["--api", API, "--web", WEB, "--supabase", PROJECT]


def deployment(**wrong: object) -> httpx.MockTransport:
    def api(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/internal/health":
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "env": wrong.get("env", "staging"),
                    "database": "ok",
                    "queue": {"waiting": 0, "oldest_seconds": wrong.get("oldest_seconds", 0)},
                },
            )
        if path == "/internal/dev/people":
            return httpx.Response(200 if wrong.get("local_sign_in") else 404, json=[])
        if path == "/v1/me" and request.method == "OPTIONS":
            allowed = {} if wrong.get("origin_refused") else {"origin": request.headers["origin"]}
            return httpx.Response(
                200, headers={f"access-control-allow-{k}": v for k, v in allowed.items()}
            )
        if path == "/v1/me":
            return httpx.Response(
                401,
                content=b'{"title": "Missing or invalid credentials"}',
                headers={"content-type": "application/problem+json"},
            )
        return httpx.Response(404)

    def web(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/login":
            return httpx.Response(200, text="<html><main><form></form></main></html>")
        if path == "/manifest.webmanifest":
            return httpx.Response(200, json={"name": "DealerAI", "start_url": "/"})
        if path == "/dev-login" and wrong.get("local_page"):
            return httpx.Response(200, text="<html>Local sign-in</html>")
        return httpx.Response(307, headers={"location": f"/login?next={path}"})

    def project(request: httpx.Request) -> httpx.Response:
        keys = [] if wrong.get("no_keys") else [{"kid": "one", "kty": "EC", "alg": "ES256"}]
        return httpx.Response(200, json={"keys": keys})

    def answer(request: httpx.Request) -> httpx.Response:
        origin = f"{request.url.scheme}://{request.url.host}"
        return {API: api, WEB: web, PROJECT: project}[origin](request)

    return httpx.MockTransport(answer)


def test_a_deployment_that_is_fit_passes_and_says_what_it_checked(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert smoke.main(EVERYTHING, transport=deployment()) == 0
    said = capsys.readouterr().out
    assert "FAIL" not in said
    assert said.count("ok  ") == 12
    assert said.rstrip().endswith("fit to use")


def test_only_the_api_can_be_asked_about(capsys: pytest.CaptureFixture[str]) -> None:
    assert smoke.main(["--api", API], transport=deployment()) == 0
    assert capsys.readouterr().out.count("ok  ") == 6


@pytest.mark.parametrize(
    ("wrong", "named"),
    [
        ({"env": "local"}, "it knows it is not a laptop"),
        ({"oldest_seconds": 900}, "is the worker running?"),
        ({"local_sign_in": True}, "the local sign-in is not there"),
        ({"origin_refused": True}, f"WEB_ORIGINS does not list {WEB}"),
        ({"local_page": True}, "NEXT_PUBLIC_DEV_AUTH is set"),
        ({"no_keys": True}, "the project publishes the keys it signs with"),
    ],
    ids=[
        "an API that thinks it is a laptop",
        "a queue nobody is working",
        "a local sign-in left reachable",
        "a web origin the API does not allow",
        "a web build with the local sign-in in it",
        "a project that publishes no keys",
    ],
)
def test_each_thing_wrong_fails_by_name(
    wrong: dict[str, object], named: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert smoke.main(EVERYTHING, transport=deployment(**wrong)) == 1
    said = capsys.readouterr().out
    failures = [line for line in said.splitlines() if line.startswith("FAIL")]
    assert len(failures) == 1, said
    assert named in failures[0]
    assert "1 thing(s) to fix" in said


def test_a_deployment_that_cannot_be_reached_fails_without_a_traceback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def nobody(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    assert smoke.main(["--api", API], transport=httpx.MockTransport(nobody)) == 1
    assert "could not be reached" in capsys.readouterr().out
