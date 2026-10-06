"""Is this deployment fit to be used?

    npm run smoke -- --api https://… [--web https://…] [--supabase https://….supabase.co]

Read-only: every request is a GET or a preflight, and none carries a credential.
Run from a laptop after a deploy (docs/sales/10-staging.md), it says by name
what is wrong before a person finds out by signing in.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

import httpx

#: Seconds something may have waited for the worker before it is called behind.
WORKER_BEHIND_AFTER = 300


class Report:
    def __init__(self) -> None:
        self.failed = 0

    def check(self, name: str, ok: bool, otherwise: str = "") -> None:
        if ok:
            print(f"ok    {name}")
        else:
            print(f"FAIL  {name}" + (f" — {otherwise}" if otherwise else ""))
            self.failed += 1


def check_api(client: httpx.Client, report: Report, api: str, web: str | None) -> None:
    health = client.get(f"{api}/internal/health")
    body = health.json() if health.status_code == 200 else {}
    report.check(
        "the API answers and reaches its database",
        body.get("database") == "ok",
        f"{health.status_code} from /internal/health",
    )
    report.check(
        "it knows it is not a laptop",
        body.get("env") in {"staging", "production"},
        f"ENV is {body.get('env')!r}",
    )
    queue = body.get("queue") or {}
    report.check(
        "nothing has waited five minutes for the worker",
        queue.get("oldest_seconds", WORKER_BEHIND_AFTER) < WORKER_BEHIND_AFTER,
        f"{queue.get('waiting')} waiting, the oldest for {queue.get('oldest_seconds')} s: "
        "is the worker running?",
    )
    report.check(
        "the local sign-in is not there",
        client.get(f"{api}/internal/dev/people").status_code == 404,
        "/internal/dev/people answered: ENV is local somewhere",
    )
    report.check(
        "the API's own documentation is not public",
        client.get(f"{api}/docs").status_code == 404,
        "/docs answered",
    )
    me = client.get(f"{api}/v1/me")
    report.check(
        "nobody is let in without a session",
        me.status_code == 401 and "problem+json" in me.headers.get("content-type", ""),
        f"{me.status_code} from /v1/me",
    )
    if web:
        preflight = client.options(
            f"{api}/v1/me",
            headers={
                "Origin": web,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization,x-tenant-id",
            },
        )
        report.check(
            "the web app's origin may call the API",
            preflight.headers.get("access-control-allow-origin") == web,
            f"WEB_ORIGINS does not list {web}",
        )


def check_web(client: httpx.Client, report: Report, web: str) -> None:
    login = client.get(f"{web}/login")
    report.check(
        "the sign-in page is served",
        login.status_code == 200 and "<form" in login.text,
        f"{login.status_code} from /login",
    )
    inside = client.get(f"{web}/a-workspace/inbox")
    report.check(
        "a page inside a workspace sends somebody signed out to sign in",
        inside.is_redirect and "/login" in inside.headers.get("location", ""),
        f"{inside.status_code} from a workspace's inbox",
    )
    local = client.get(f"{web}/dev-login")
    report.check(
        "the local sign-in page is behind the real one",
        local.is_redirect and "/login" in local.headers.get("location", ""),
        "/dev-login is open: NEXT_PUBLIC_DEV_AUTH is set in this build",
    )
    manifest = client.get(f"{web}/manifest.webmanifest")
    installable = manifest.status_code == 200 and bool(manifest.json().get("start_url"))
    report.check(
        "the app can be installed", installable, f"{manifest.status_code} from the manifest"
    )


def check_project(client: httpx.Client, report: Report, supabase: str) -> None:
    answer = client.get(f"{supabase}/auth/v1/.well-known/jwks.json")
    keys = answer.json().get("keys", []) if answer.status_code == 200 else []
    report.check(
        "the project publishes the keys it signs with",
        bool(keys),
        "none: it still signs with a shared secret, which the API refuses outside a "
        "laptop. Supabase → Project settings → JWT keys → migrate to signing keys",
    )


def main(argv: Sequence[str] | None = None, transport: httpx.BaseTransport | None = None) -> int:
    parser = argparse.ArgumentParser(description="Is this deployment fit to be used?")
    parser.add_argument("--api", required=True, help="where the API is")
    parser.add_argument("--web", help="where the web app is")
    parser.add_argument("--supabase", help="the Supabase project's address")
    args = parser.parse_args(argv)
    web = args.web.rstrip("/") if args.web else None
    report = Report()
    try:
        with httpx.Client(timeout=15, transport=transport) as client:
            check_api(client, report, args.api.rstrip("/"), web)
            if web:
                check_web(client, report, web)
            if args.supabase:
                check_project(client, report, args.supabase.rstrip("/"))
    except httpx.TransportError as exc:
        report.check("everything answers", False, f"{exc.request.url} could not be reached")
    print("fit to use" if not report.failed else f"{report.failed} thing(s) to fix")
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
