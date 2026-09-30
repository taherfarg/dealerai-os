# Sales S7 — Pilot readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** the product leaves this machine. Pollux's people sign in with their own accounts and are
invited in with the right scope; the app installs on a phone and pushes; every screen reads right in
Arabic and works with a keyboard and a screen reader; a Playwright suite walks the exit paths on
every change; and a staging stack runs all of it against the hosted Supabase project — so that the
week S5 connects the real number, two reps start the pilot and the eight success criteria in
[00](../00-prd.md) §7 are measured on Pollux.

**How this plan is split.** S7 is five pieces of work that can each be shipped and demonstrated on
their own, so it is five parts. Part A is planned in full below. The rest follow this project's
convention from [09](../09-implementation-plan.md): each is written at pickup, appended to this file
under its own heading, with its own exit run.

| Part | What | Exit | Needs |
|---|---|---|---|
| **A** | Sign-in and joining ([08](../08-screens.md) §14) | An owner creates the workspace and invites a salesperson by a link; the salesperson joins with the invited email and lands in the inbox with the invited role and teams — in both languages, locally | — |
| **B** | Installable app and push ([07](../07-frontend.md) §8) | Installed on a phone; a customer who writes wakes the assigned salesperson's phone | A |
| **C** | Arabic and accessibility pass ([08](../08-screens.md) §15.9) | Every screen reviewed in Arabic at 375 px and with a keyboard and a screen reader; the English-in-Arabic items the S4 and S6 reviews left are gone | — |
| **D** | Playwright suite and staging | The exit paths run on every pull request; staging runs the API, the worker and the web app against the hosted project, and a real sign-in completes there | A, the region decision (Q1) |
| **E** | The pilot | Two reps on Pollux's real number for four weeks; the eight criteria measured | S5, B, D |

**The founder track (dashboards, not code)** — like Meta's in [09](../09-implementation-plan.md),
these are the owner's, and Parts D and E wait on them:

| For | Step |
|---|---|
| D | Decide Q1: keep the Supabase project in Tokyo or move it to Mumbai before real customer data |
| D | Supabase → Authentication: custom SMTP (the built-in sender rate-limits at once — the gap in [../../README.md](../../README.md)), the site URL and redirect URLs for staging |
| D | Google Cloud: an OAuth client; Supabase → Providers → Google with its id and secret |
| E | Meta verification and app review, then S5 |

---

# Part A — Sign-in and joining

**Goal:** Khalid signs up, creates Pollux's workspace and invites Layla by a link he sends her on
WhatsApp; Layla creates her account with the invited email — or signs in with Google — and lands in
the inbox as a salesperson in Local sales, seeing that team's unassigned customers. Every screen on
the way speaks Arabic and English, and none of them says whether an email has an account.

**Architecture:** Supabase Auth stays the identity provider and the API stays the only thing that
decides membership. An invitation remains a signed, expiring token — no table — that now names one
email address, a role and teams; joining is one `security definer` function that writes the
membership, the team memberships and the person's profile together, and refuses nothing it has
already done. Locally, where there is no Supabase Auth, the dev sign-in learns to create a new
person the way Supabase would, so the whole path runs here and in Playwright. The real credential
round trip happens on staging, in Part D.

**Tech stack:** Postgres 17 · FastAPI · PyJWT · Next.js 16 app router · `@supabase/ssr` · Vitest ·
pytest.

**Before you start:**

- Docker Desktop running; `npm run db:up`. Branch `sales/phase-1`.
- **Stop the worker before running the suite**, and re-seed after every test run — the suite deletes
  the seeded workspace.
- Read [08](../08-screens.md) §14, [06](../06-api-contract.md) §1–§2, and
  [01](../01-architecture.md) §7 (the local sign-in).
- As in S3–S6: backend modules are given whole; screen tasks give the parts that carry a decision,
  and tests as their names and assertions.

**Found while reading the code for this plan** — fixed in the tasks named:

| Found | Why it matters | Task |
|---|---|---|
| Accepting an invitation never checks that the person signed in is the person invited | Anybody holding the link joins with any account: a forwarded WhatsApp message is a way in | A1 |
| Nothing writes `profiles` for a real person; only the seed does | A real salesperson is nameless on the Team screen, the dashboard, and every "Assigned to" line | A1 |
| An invitation defaults to `marketer` — DealerAI OS's content role — and carries no teams | A salesperson invited with the defaults is in no team: no unassigned customers, and routing never gives them a chat | A1 |
| Two people accepting at once can both pass `accept_invite`'s check and one insert fails | A 500 on the second click of a double-tap | A1 |
| The dev sign-in knows only the seeded five | The joining path cannot run locally or in Playwright | A2 |
| The sign-in pages sit outside the locale provider and are English-only | The first screen a rep sees is the one screen in the wrong language | A3 |
| There is no sign-up page and no `/auth/callback`, though the gate already lists both as public | Nobody can create an account, confirm an email, or come back from Google | A4 |
| After signing in, `/login` always goes to `/`, dropping `next` | A shared link — or an invitation — is lost on the way through sign-in | A4 |
| The root page sends someone with no workspace to `/onboarding`, which does not exist: `[tenant]` catches it as a workspace called "onboarding" | A new owner's first screen is an error | A5 |
| The API verifies HS256 with the project secret only; a Supabase project can sign with asymmetric keys it publishes as JWKS | If the hosted project does, every real token is refused — checked on the first real sign-in, in Part D | D |

## What Part A does not build

| Item | Arrives with |
|---|---|
| Emails from DealerAI — invitations sent for you | Not in Phase 1. The manager sends the link on WhatsApp, which is where Pollux's people already are; the Team screen has a Send on WhatsApp button |
| Forgotten password | Part D, with custom SMTP: Supabase's reset email is the same sender that rate-limits today |
| A profile screen to change your own name | Later. The name comes from sign-up or Google, and a manager sees the email when there is none |
| Revoking an invitation before it is used | Later. An invitation lasts seven days and works once, for one email |
| JWKS verification | Part D, if the hosted project signs asymmetrically |

## File structure

| File | Responsibility |
|---|---|
| `supabase/migrations/0013_sales_joining.sql` | **Create.** `app.remember_profile()`; `app.accept_invite()` with teams, profile and no race |
| `apps/api/src/dealerai/core/security.py` | **Modify.** `mint_test_token(name=…)` puts `user_metadata.full_name` in the token, as Supabase does |
| `apps/api/src/dealerai/routes/tenants.py` | **Modify.** Invitations for one email, into teams, naming the workspace; joining returns where to go; a new workspace remembers its owner |
| `apps/api/src/dealerai/routes/dev.py` | **Modify.** A local session for somebody new |
| `apps/web/app/(auth)/layout.tsx` | **Create.** The locale for every page outside a workspace |
| `apps/web/app/(auth)/login/page.tsx`, `components/auth/LoginForm.tsx` | **Modify / Create.** Bilingual, `next` kept, Google |
| `apps/web/app/(auth)/signup/page.tsx`, `components/auth/SignupForm.tsx` | **Create.** An account, confirmed by email |
| `apps/web/components/auth/GoogleButton.tsx` | **Create.** Continue with Google |
| `apps/web/app/auth/callback/route.ts` | **Create.** The one-time code from an email link or from Google |
| `apps/web/app/(auth)/onboarding/page.tsx`, `components/auth/CreateWorkspace.tsx` | **Create.** A first workspace |
| `apps/web/app/(auth)/accept-invite/page.tsx`, `components/auth/JoinInvitation.tsx` | **Create.** Joining |
| `apps/web/app/(auth)/dev-login/page.tsx`, `lib/dev-auth.ts` | **Modify.** Somebody new; `next` kept |
| `apps/web/proxy.ts` | **Modify.** `/accept-invite` is public; `next` survives both gates |
| `apps/web/lib/auth/next.ts`, `lib/jwt.ts`, `lib/invitation.ts`, `lib/slug.ts`, `lib/api/joining.ts` | **Create.** Safe redirects, reading a token, an invitation, a slug, and the two calls made outside a workspace |
| `apps/web/lib/auth/token.ts` | **Modify.** `signedInEmail()` |
| `apps/web/components/settings/InviteForm.tsx`, `TeamSettings.tsx`, `lib/api/hooks.ts` | **Create / Modify.** Inviting from the Team screen |
| `apps/web/messages/{en,ar}.ts` | **Modify.** Every string Part A shows |

---

## Task A1: An invitation is for one person, into teams, and joining remembers who they are

**Files:**
- Create: `supabase/migrations/0013_sales_joining.sql`
- Modify: `apps/api/src/dealerai/core/security.py`, `apps/api/src/dealerai/routes/tenants.py`
- Test: `apps/api/tests/test_tenants.py`

- [ ] **Step 1: Let a test token carry a name, as Supabase's does**

In `core/security.py`, `mint_test_token` gains a keyword and one claim:

```python
def mint_test_token(
    user_id: UUID,
    *,
    secret: str,
    email: str | None = None,
    name: str | None = None,
    expires_in_seconds: int = 3600,
) -> str:
    ...
    if email:
        payload["email"] = email
    if name:
        # Where Supabase puts what somebody typed on sign-up, and what Google
        # calls them.
        payload["user_metadata"] = {"full_name": name}
    return jwt.encode(payload, secret, algorithm="HS256")
```

- [ ] **Step 2: Write the failing tests**

In `tests/test_tenants.py`, `auth()` gains the two claims, and two helpers are added beside `_exec`:

```python
def auth(
    user_id: uuid.UUID,
    tenant_id: uuid.UUID | None = None,
    *,
    email: str | None = None,
    name: str | None = None,
) -> dict[str, str]:
    token = mint_test_token(user_id, secret=SECRET, email=email, name=name)
    headers = {"Authorization": f"Bearer {token}"}
    if tenant_id is not None:
        headers["X-Tenant-Id"] = str(tenant_id)
    return headers


def _fetch(sql: str, *args: object) -> list[asyncpg.Record]:
    async def run() -> list[asyncpg.Record]:
        conn = await asyncpg.connect(get_settings().migration_dsn)
        try:
            return list(await conn.fetch(sql, *args))
        finally:
            await conn.close()

    return asyncio.run(run())


INVITED = "new@dealer.test"


def _invite(client: TestClient, **body: object) -> str:
    response = client.post(
        f"/v1/tenants/{TENANT_A}/invites",
        json={"email": INVITED, "role": "sales", **body},
        headers=auth(USER_A, TENANT_A),
    )
    assert response.status_code == 201, response.text
    return str(response.json()["token"])


def _join(client: TestClient, token: str, **claims: str) -> Any:
    return client.post(
        "/v1/invites/accept",
        json={"token": token},
        headers=auth(USER_B, **({"email": INVITED} | claims)),
    )
```

The two existing accept tests now accept as the invited email
(`test_owner_can_invite_and_the_link_is_redeemable` through `_invite` and `_join`;
`test_replaying_an_invite_neither_duplicates_nor_reroles` with `auth(USER_B, email="b@dealer.test")`
on both accepts). New tests:

```python
def test_a_forwarded_invitation_is_refused(client: TestClient) -> None:
    """Anybody holding the link joined with any account."""
    refused = _join(client, _invite(client), email="someone.else@dealer.test")
    assert refused.status_code == 403
    assert not _fetch(
        "select 1 from memberships where tenant_id = $1 and user_id = $2", TENANT_A, USER_B
    )


def test_an_address_is_compared_as_an_address(client: TestClient) -> None:
    token = _invite(client, email="New@Dealer.test")
    assert _join(client, token, email="new@dealer.TEST").status_code == 200


def test_joining_puts_them_in_the_invited_teams(client: TestClient) -> None:
    team = uuid.uuid4()
    _exec("insert into teams (id, tenant_id, name) values ($1, $2, 'Local')", team, TENANT_A)
    assert _join(client, _invite(client, team_ids=[str(team)])).status_code == 200
    rows = _fetch("select team_id from team_members where user_id = $1", USER_B)
    assert [row["team_id"] for row in rows] == [team]


def test_an_invitation_names_only_this_workspaces_teams(client: TestClient) -> None:
    theirs = uuid.uuid4()
    _exec("insert into teams (id, tenant_id, name) values ($1, $2, 'Export')", theirs, TENANT_B)
    response = client.post(
        f"/v1/tenants/{TENANT_A}/invites",
        json={"email": INVITED, "role": "sales", "team_ids": [str(theirs)]},
        headers=auth(USER_A, TENANT_A),
    )
    assert response.status_code == 422


def test_joining_remembers_who_they_are(client: TestClient) -> None:
    """Only the seed wrote profiles: a real salesperson was nameless everywhere."""
    _join(client, _invite(client), name="Layla Hassan")
    [profile] = _fetch("select email, full_name from profiles where id = $1", USER_B)
    assert (profile["email"], profile["full_name"]) == (INVITED, "Layla Hassan")


def test_creating_a_workspace_remembers_its_owner(client: TestClient) -> None:
    response = client.post(
        "/v1/tenants",
        json={"name": "Test Motors", "slug": f"test-{uuid.uuid4().hex[:8]}"},
        headers=auth(USER_B, email="owner@dealer.test", name="Khalid Al Suwaidi"),
    )
    assert response.status_code == 201, response.text
    [profile] = _fetch("select full_name from profiles where id = $1", USER_B)
    assert profile["full_name"] == "Khalid Al Suwaidi"


def test_the_link_names_the_workspace_and_joining_says_where_to_go(client: TestClient) -> None:
    token = _invite(client)
    claims = jwt.decode(token, options={"verify_signature": False})
    tenant = client.get(f"/v1/tenants/{TENANT_A}", headers=auth(USER_A, TENANT_A)).json()
    assert claims["tenant_name"] == tenant["name"]
    assert claims["email"] == INVITED
    assert _join(client, token).json()["tenant_slug"] == tenant["slug"]


def test_an_invitation_is_for_a_salesperson_unless_it_says_otherwise(client: TestClient) -> None:
    response = client.post(
        f"/v1/tenants/{TENANT_A}/invites",
        json={"email": INVITED},
        headers=auth(USER_A, TENANT_A),
    )
    assert response.json()["role"] == "sales"
```

(`import jwt` and `from typing import Any` join the imports.)

- [ ] **Step 3: Run them and see them fail**

Run: `cd apps/api && uv run pytest tests/test_tenants.py -q`
Expected: the new tests FAIL — the forwarded invitation is accepted (200), no team rows, no profile,
no `tenant_name` claim, and `role` defaults to `marketer`.

- [ ] **Step 4: The migration**

`supabase/migrations/0013_sales_joining.sql`:

```sql
-- =============================================================================
-- 0013_sales_joining — S7 Part A: somebody who joins a workspace, as they are.
-- Only the seed wrote `profiles`, so anybody who really signed up was nameless
-- on every screen; an invitation carried a role and nothing else, so a
-- salesperson arrived in no team, saw no unassigned customer and was routed no
-- chat. See docs/sales/08-screens.md § 14.
-- =============================================================================

-- Who they are, from their own sign-in: the address is Supabase's, the name is
-- what they typed on sign-up (or Google's). A name they already have is kept.
create or replace function app.remember_profile(p_user uuid, p_email text, p_name text)
returns void
language sql
security definer
set search_path = public, pg_temp
as $$
  insert into profiles (id, email, full_name)
  values (p_user, p_email, nullif(btrim(p_name), ''))
  on conflict (id) do update
     set email = coalesce(excluded.email, profiles.email),
         full_name = coalesce(profiles.full_name, excluded.full_name),
         updated_at = now();
$$;

drop function if exists app.accept_invite(uuid, uuid, text);

-- Joining, all of it or none of it. Somebody already a member keeps their role
-- and teams — replaying a link can neither promote nor move anyone — and two
-- clicks at once are one join, not a unique violation.
create or replace function app.accept_invite(
    p_tenant uuid,
    p_user   uuid,
    p_role   text,
    p_teams  uuid[],
    p_email  text,
    p_name   text
)
returns text
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    existing text;
begin
    perform app.remember_profile(p_user, p_email, p_name);

    insert into memberships (tenant_id, user_id, role)
    values (p_tenant, p_user, p_role)
    on conflict (tenant_id, user_id) do nothing;
    if not found then
        select role into existing
          from memberships where tenant_id = p_tenant and user_id = p_user;
        return existing;
    end if;

    -- This workspace's teams only, whatever the token says.
    insert into team_members (tenant_id, team_id, user_id)
    select p_tenant, t.id, p_user
      from teams t
     where t.tenant_id = p_tenant and t.id = any (coalesce(p_teams, '{}'))
    on conflict do nothing;
    return p_role;
end;
$$;

revoke all on function app.remember_profile(uuid, text, text) from public;
revoke all on function app.accept_invite(uuid, uuid, text, uuid[], text, text) from public;
grant execute on function app.remember_profile(uuid, text, text) to dealerai_app;
grant execute on function app.accept_invite(uuid, uuid, text, uuid[], text, text) to dealerai_app;
```

- [ ] **Step 5: The routes**

In `routes/tenants.py` — imports gain `Unusable` from `..core.errors` and `AuthedUser` from
`..core.security`. The models:

```python
#: Loose on purpose: Supabase decides what an address is. This only stops a
#: name typed into the email box from minting a link nobody can accept.
EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class InviteCreate(BaseModel):
    email: str = Field(pattern=EMAIL, max_length=254)
    role: Role = "sales"
    team_ids: list[UUID] = Field(default_factory=list, max_length=20)


class JoinedOut(BaseModel):
    tenant_id: UUID
    tenant_slug: str
    role: Role


def _name(user: AuthedUser) -> str | None:
    """What they called themselves on sign-up, or what Google calls them."""
    metadata = user.claims.get("user_metadata") or {}
    return metadata.get("full_name") or metadata.get("name")
```

`create_tenant` remembers its owner, inside the `system_session` block, after the tenant exists:

```python
        await conn.execute(
            "select app.remember_profile($1, $2, $3)", user.id, user.email, _name(user)
        )
```

`create_invite`, after the role check:

```python
    teams = list(dict.fromkeys(body.team_ids))
    async with tenant_session(ctx.tenant_id) as conn:
        tenant = await conn.fetchrow("select name from tenants where id = $1", tenant_id)
        known = await conn.fetchval(
            "select count(*) from teams where id = any($1::uuid[])", teams
        )
    if known != len(teams):
        raise Unusable("an invitation can only name this workspace's teams")

    expires_at = datetime.now(UTC) + timedelta(days=INVITE_TTL_DAYS)
    token = jwt.encode(
        {
            "kind": "invite",
            "tenant_id": str(tenant_id),
            # For the page that opens the link, before its reader belongs anywhere.
            "tenant_name": tenant["name"],
            "role": body.role,
            "email": body.email.strip().lower(),
            "teams": [str(team) for team in teams],
            "exp": int(expires_at.timestamp()),
        },
        _invite_secret(),
        algorithm="HS256",
    )
```

`accept_invite`, whole:

```python
@router.post("/invites/accept", response_model=JoinedOut)
async def accept_invite(body: InviteAccept, user: CurrentUser) -> JoinedOut:
    try:
        claims = jwt.decode(body.token, _invite_secret(), algorithms=["HS256"])
    except jwt.ExpiredSignatureError as exc:
        raise Unauthenticated("this invitation has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise Unauthenticated("invalid invitation") from exc

    if claims.get("kind") != "invite":
        raise Unauthenticated("invalid invitation")
    # A link forwarded on WhatsApp is not an invitation for whoever opens it.
    if str(claims.get("email") or "").lower() != (user.email or "").strip().lower():
        raise Forbidden("this invitation is for another email address")

    tenant_id = UUID(claims["tenant_id"])
    async with system_session() as conn:
        role = await conn.fetchval(
            "select app.accept_invite($1, $2, $3, $4::uuid[], $5, $6)",
            tenant_id,
            user.id,
            claims["role"],
            [UUID(team) for team in claims.get("teams") or []],
            user.email,
            _name(user),
        )
        # A member now, so the one-user read finds it.
        slug = await conn.fetchval(
            "select slug from app.tenants_for_user($1) where id = $2", user.id, tenant_id
        )
    return JoinedOut(tenant_id=tenant_id, tenant_slug=slug, role=role)
```

- [ ] **Step 6: Run them and see them pass**

Run: `cd apps/api && uv run pytest tests/test_tenants.py tests/test_visibility.py -q && uv run mypy src && uv run ruff check . && uv run ruff format --check .`
Expected: PASS.

- [ ] **Step 7: The contract, now — Tasks A5–A7 compile against it**

Run: `npm run api-types`
Expected: `openapi.json` and `schema.ts` gain `JoinedOut`, and `InviteCreate`'s `team_ids` and
`sales` default. `npm run check --workspace web` still passes: nothing reads them yet.

- [ ] **Step 8: Commit**

```bash
git add supabase/migrations/0013_sales_joining.sql apps/api/src/dealerai/core/security.py apps/api/src/dealerai/routes/tenants.py apps/api/tests/test_tenants.py apps/web/lib/api/openapi.json apps/web/lib/api/schema.ts
git commit -m "feat(sales): an invitation is for one person, into teams, and joining remembers them"
```

---

## Task A2: A local session for somebody new

**Files:**
- Create: `apps/web/lib/auth/next.ts`
- Modify: `apps/api/src/dealerai/routes/dev.py`, `apps/web/lib/dev-auth.ts`,
  `apps/web/app/(auth)/dev-login/page.tsx`, `apps/web/proxy.ts`
- Test: `apps/api/tests/test_dev_session.py`, `apps/web/lib/auth/next.test.ts`

Local Postgres has no Supabase Auth, so nobody but the seeded five can sign in, and an invitation
can never be accepted here. Supabase creates a person on sign-up; locally the dev route does the
same, into the `auth.users` shim — still behind both locks (mounted only when `ENV=local`, and every
handler re-checks).

- [ ] **Step 1: Write the failing test**

`test_an_unknown_email_gets_nothing` is replaced:

```python
async def test_somebody_new_gets_a_session_and_no_workspace(
    db: None, su: asyncpg.Connection
) -> None:
    """What Supabase does on sign-up, so an invitation can be accepted locally."""
    session = await dev.create_session(
        dev.DevSessionIn(email="Layla@Pollux.test", name="Layla Hassan")
    )
    user = decode_supabase_jwt(session.access_token)
    assert user.email == "layla@pollux.test"
    assert user.claims["user_metadata"] == {"full_name": "Layla Hassan"}
    assert (session.tenant_id, session.tenant_slug) == (None, None)
    assert await su.fetchval("select email from auth.users where id = $1", user.id) == (
        "layla@pollux.test"
    )
    again = await dev.create_session(dev.DevSessionIn(email="layla@pollux.test"))
    assert decode_supabase_jwt(again.access_token).id == user.id, "one person, one id"
```

(`import asyncpg` joins the imports.)

- [ ] **Step 2: Run it and see it fail**

Run: `cd apps/api && uv run pytest tests/test_dev_session.py -q`
Expected: FAIL — `NotFound: no seeded person with that email`.

- [ ] **Step 3: The route**

```python
from uuid import NAMESPACE_URL, UUID, uuid5

import asyncpg

#: Ids for people created here, stable per address: a re-seed or a restart keeps
#: whatever they joined.
_NEWCOMERS = uuid5(NAMESPACE_URL, "dealerai-os/dev/newcomers")


class DevSessionIn(BaseModel):
    email: str
    name: str | None = None


class DevSession(BaseModel):
    access_token: str
    #: The seeded workspace for the seeded five; nobody's for anybody else.
    tenant_id: UUID | None
    tenant_slug: str | None


@router.post("/session", response_model=DevSession)
async def create_session(body: DevSessionIn) -> DevSession:
    _local_only()
    settings = get_settings()
    if not settings.supabase_jwt_secret:
        raise AuthUnavailable("SUPABASE_JWT_SECRET is not set")
    email = body.email.strip().lower()
    seeded = {person_email(name): name for name, *_ in PEOPLE}.get(email)
    if seeded:
        token = mint_test_token(
            person_id(seeded),
            secret=settings.supabase_jwt_secret,
            email=email,
            name=seeded,
            expires_in_seconds=SESSION_SECONDS,
        )
        return DevSession(access_token=token, tenant_id=TENANT, tenant_slug=TENANT_SLUG)

    # Somebody new: where Supabase would put them on sign-up. The migration
    # role, because the app role may not write auth.users — nor should it.
    user_id = uuid5(_NEWCOMERS, email)
    conn = await asyncpg.connect(settings.migration_dsn)
    try:
        await conn.execute(
            "insert into auth.users (id, email) values ($1, $2) on conflict do nothing",
            user_id,
            email,
        )
    finally:
        await conn.close()
    token = mint_test_token(
        user_id,
        secret=settings.supabase_jwt_secret,
        email=email,
        name=body.name,
        expires_in_seconds=SESSION_SECONDS,
    )
    return DevSession(access_token=token, tenant_id=None, tenant_slug=None)
```

`NotFound` leaves the imports only if nothing else uses it (`_local_only` does — it stays).

- [ ] **Step 4: Where to go after signing in — only somewhere in this app**

The dev sign-in is the first page to honour `next`; the real ones follow in A3 and A4. Test first,
`lib/auth/next.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { safeNext } from "./next";

describe("safeNext", () => {
  it("keeps a path in this app", () => {
    expect(safeNext("/accept-invite?token=abc")).toBe("/accept-invite?token=abc");
  });
  it.each(["//evil.example", "/\\evil.example", "https://evil.example", "evil", "", null])(
    "sends %s home: a sign-in must not be a way to send somebody elsewhere",
    (value) => {
      expect(safeNext(value)).toBe("/");
    },
  );
});
```

Run: `npm run test --workspace web -- lib/auth/next.test.ts` — Expected: FAIL, module missing. Then
`lib/auth/next.ts`:

```ts
/**
 * Where to go after signing in: only somewhere in this app. `next` arrives in
 * a URL anybody can write, so without this a sign-in link is a way to send a
 * rep to a look-alike site straight after they typed their password.
 */
export function safeNext(value: string | null | undefined): string {
  if (!value || !value.startsWith("/") || value.startsWith("//") || value.startsWith("/\\")) {
    return "/";
  }
  return value;
}
```

- [ ] **Step 5: The page and the gate**

`lib/dev-auth.ts`: `startDevSession(email: string, name?: string): Promise<string | null>` sends
`{ email, name }` and returns `session.tenant_slug` (null for somebody new).

`dev-login/page.tsx` reads `next` (with `useSearchParams`, inside `Suspense`) and, under the seeded
five, adds a small form — email and name — titled *Somebody new*:

```tsx
const next = safeNext(params.get("next"));
async function signIn(email: string, name?: string) {
  try {
    const slug = await startDevSession(email, name);
    // A link they were on — an invitation — first; then their workspace; then
    // the root, which sends somebody with none to create one.
    router.push(params.get("next") ? next : slug ? `/${slug}` : "/");
    router.refresh();
  } catch (e) {
    setError((e as Error).message);
  }
}
```

`proxy.ts`, the dev branch keeps where they were going:

```ts
const url = request.nextUrl.clone();
url.pathname = "/dev-login";
url.search = "";
url.searchParams.set("next", `${pathname}${request.nextUrl.search}`);
return NextResponse.redirect(url);
```

- [ ] **Step 6: Run the tests**

Run: `cd apps/api && uv run pytest tests/test_dev_session.py -q` then
`npm run check --workspace web`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/api/src/dealerai/routes/dev.py apps/api/tests/test_dev_session.py apps/web/lib/dev-auth.ts "apps/web/app/(auth)/dev-login/page.tsx" apps/web/proxy.ts apps/web/lib/auth/next.ts apps/web/lib/auth/next.test.ts
git commit -m "feat(sales): a local session for somebody new, so joining runs here"
```

---

## Task A3: The pages outside a workspace speak Arabic

**Files:**
- Create: `apps/web/app/(auth)/layout.tsx`, `apps/web/components/auth/LoginForm.tsx`
- Modify: `apps/web/app/(auth)/login/page.tsx`, `apps/web/messages/{en,ar}.ts`
- Test: `apps/web/components/auth/LoginForm.test.tsx`

- [ ] **Step 1: Write the failing test**

`components/auth/LoginForm.test.tsx` — `vi.mock("@/lib/supabase/client")` returning
`signInWithPassword`, and `vi.mock("next/navigation")` returning `push`/`refresh` and the search
params:

- "labels itself in Arabic" — under `<LocaleProvider locale="ar">`, the email field is labelled
  "البريد الإلكتروني" and the button reads "تسجيل الدخول".
- "shows Supabase's own sentence, which does not say which half was wrong" — a rejected sign-in
  renders "Invalid login credentials" in the alert, unchanged.
- "goes where it was sent" — with `?next=/pollux-motors/inbox`, a successful sign-in pushes that
  path; with `?next=//evil.example`, it pushes `/`.

- [ ] **Step 2: Run it and see it fail**

Run: `npm run test --workspace web -- components/auth/LoginForm.test.tsx`
Expected: FAIL — the component does not exist.

- [ ] **Step 3: The layout**

`app/(auth)/layout.tsx`:

```tsx
import { cookies } from "next/headers";
import { LocaleToggle } from "@/components/LocaleToggle";
import type { Locale } from "@/lib/i18n";
import { LocaleProvider } from "@/lib/i18n-client";

/** Every page outside a workspace — sign-in, sign-up, joining, the first
 *  workspace — in the language the cookie says, like the pages inside one. */
export default async function AuthLayout({ children }: { children: React.ReactNode }) {
  const locale = ((await cookies()).get("locale")?.value ?? "en") as Locale;
  return (
    <LocaleProvider locale={locale}>
      <main className="mx-auto flex min-h-screen w-full max-w-sm flex-col justify-center gap-6 p-6">
        <div className="flex justify-end">
          <LocaleToggle locale={locale} />
        </div>
        {children}
      </main>
    </LocaleProvider>
  );
}
```

- [ ] **Step 4: The form**

`components/auth/LoginForm.tsx` is today's `login/page.tsx` form, with every string through `useT()`,
`router.push(safeNext(params.get("next")))` on success, and a *Create an account* link to
`/signup?next=…` carrying `next` (the page arrives in A4). The page becomes
`<Suspense><LoginForm /></Suspense>`. The Supabase error stays verbatim — the existing comment
explains why.

- [ ] **Step 5: The strings**

Added to `messages/en.ts` and `messages/ar.ts` (Tasks A3–A7 use them):

| Key | English | Arabic |
|---|---|---|
| `auth.signIn` | Sign in | تسجيل الدخول |
| `auth.signInTitle` | Sign in to your workspace. | سجّل الدخول إلى مساحة عملك. |
| `auth.email` | Email | البريد الإلكتروني |
| `auth.password` | Password | كلمة المرور |
| `auth.signingIn` | Signing in… | جارٍ تسجيل الدخول… |
| `auth.noAccount` | New here? | جديد هنا؟ |
| `auth.createAccount` | Create an account | أنشئ حسابًا |
| `auth.haveAccount` | Already have an account? | لديك حساب بالفعل؟ |
| `auth.or` | or | أو |
| `auth.google` | Continue with Google | المتابعة باستخدام Google |
| `auth.name` | Your name | اسمك |
| `auth.passwordRule` | At least 8 characters. | 8 أحرف على الأقل. |
| `auth.creating` | Creating… | جارٍ الإنشاء… |
| `auth.checkEmail` | Check your email: the link in it finishes creating your account. | تحقّق من بريدك: الرابط فيه يُكمل إنشاء حسابك. |
| `auth.linkFailed` | That link has expired or was already used. Sign in, or ask for a new one. | انتهت صلاحية هذا الرابط أو استُخدم من قبل. سجّل الدخول، أو اطلب رابطًا جديدًا. |
| `onboarding.title` | Create your workspace | أنشئ مساحة عملك |
| `onboarding.intro` | One workspace per dealership. You will be its owner, and invite your team next. | مساحة واحدة لكل معرض. ستكون مالكها، ثم تدعو فريقك. |
| `onboarding.name` | Dealership name | اسم المعرض |
| `onboarding.slug` | Web address | عنوان الويب |
| `onboarding.slugHint` | Lowercase letters, digits and hyphens. | أحرف إنجليزية صغيرة وأرقام وشرطات. |
| `onboarding.timezone` | Time zone | المنطقة الزمنية |
| `onboarding.currency` | Currency | العملة |
| `onboarding.languages` | Languages you sell in | لغات البيع |
| `onboarding.create` | Create workspace | إنشاء المساحة |
| `invite.title` | Invite someone | دعوة شخص |
| `invite.email` | Their email | بريده الإلكتروني |
| `invite.teams` | Teams | الفرق |
| `invite.create` | Create invitation link | إنشاء رابط الدعوة |
| `invite.ready` | Send this link. It works once, for that email, until | أرسل هذا الرابط. يعمل مرة واحدة، لهذا البريد، حتى |
| `invite.copy` | Copy link | نسخ الرابط |
| `invite.copied` | Copied | تم النسخ |
| `invite.whatsapp` | Send on WhatsApp | إرسال عبر واتساب |
| `invite.message` | You are invited to join us on DealerAI: | أنت مدعو للانضمام إلينا على DealerAI: |
| `accept.invitedTo` | You are invited to join | أنت مدعو للانضمام إلى |
| `accept.role` | Role: | الدور: |
| `accept.join` | Join | انضمام |
| `accept.joining` | Joining… | جارٍ الانضمام… |
| `accept.createAccount` | Create an account with this email | أنشئ حسابًا بهذا البريد |
| `accept.signIn` | I already have an account | لديّ حساب بالفعل |
| `accept.forEmail` | This invitation is for | هذه الدعوة موجّهة إلى |
| `accept.signedInAs` | You are signed in as | أنت مسجّل الدخول باسم |
| `accept.signOut` | Sign out and use the invited email | سجّل الخروج واستخدم البريد المدعو |
| `accept.expired` | This invitation has expired. Ask whoever sent it for a new one. | انتهت صلاحية هذه الدعوة. اطلب دعوة جديدة ممن أرسلها. |
| `accept.invalid` | This link is not an invitation. | هذا الرابط ليس دعوة. |

- [ ] **Step 6: Run the checks**

Run: `npm run check --workspace web`
Expected: PASS — `ar.ts` `satisfies` the English keys, so a missing translation fails typecheck.

- [ ] **Step 7: Commit**

```bash
git add "apps/web/app/(auth)/layout.tsx" "apps/web/app/(auth)/login/page.tsx" apps/web/components/auth/LoginForm.tsx apps/web/components/auth/LoginForm.test.tsx apps/web/messages/en.ts apps/web/messages/ar.ts
git commit -m "feat(web): the pages outside a workspace speak Arabic"
```

---

## Task A4: An account, confirmed by email or by Google, and `next` that survives

**Files:**
- Create: `apps/web/components/auth/SignupForm.tsx`, `apps/web/components/auth/GoogleButton.tsx`,
  `apps/web/app/(auth)/signup/page.tsx`, `apps/web/app/auth/callback/route.ts`
- Modify: `apps/web/proxy.ts`, `apps/web/components/auth/LoginForm.tsx`
- Test: `apps/web/components/auth/SignupForm.test.tsx`

- [ ] **Step 1: Write the failing test**

`components/auth/SignupForm.test.tsx` (Supabase and the router mocked):

- "asks Supabase for the account with the name, and a way back that keeps where they were going" —
  `signUp` receives `{ email, password, options: { data: { full_name: "Layla Hassan" },
  emailRedirectTo: "http://localhost:3000/auth/callback?next=%2Faccept-invite%3Ftoken%3Dabc" } }`.
- "says the same thing whether or not the email has an account" — `signUp` resolving with
  `{ data: { session: null, user: { identities: [] } } }` and with a new user both render
  `auth.checkEmail`, and nothing else.
- "goes straight on when no confirmation is needed" — a returned session pushes `next`.
- "fills in the invited address" — `?email=layla@pollux.test` pre-fills the field.

- [ ] **Step 2: Run it and see it fail**

Run: `npm run test --workspace web -- components/auth/SignupForm.test.tsx`
Expected: FAIL — the module is missing.

- [ ] **Step 3: Sign-up and Google**

`components/auth/SignupForm.tsx` — name, email (pre-filled from `?email=`), password
(`minLength={8}`, `autoComplete="new-password"`). The decision-carrying part:

```tsx
const next = safeNext(params.get("next"));
const { data, error } = await createClient().auth.signUp({
  email,
  password,
  options: {
    data: { full_name: name.trim() },
    emailRedirectTo: `${window.location.origin}/auth/callback?next=${encodeURIComponent(next)}`,
  },
});
if (error) return fail(error.message);
if (data.session) {
  router.push(next); // confirmation is off on this project
  router.refresh();
  return;
}
// With confirmation on, Supabase answers an address that already has an
// account exactly as it answers a new one. So does this.
setSent(true);
```

`components/auth/GoogleButton.tsx`:

```tsx
export function GoogleButton({ next }: { next: string }) {
  const t = useT();
  return (
    <button
      type="button"
      onClick={() =>
        createClient().auth.signInWithOAuth({
          provider: "google",
          options: {
            redirectTo: `${window.location.origin}/auth/callback?next=${encodeURIComponent(next)}`,
          },
        })
      }
      className="border-border min-h-11 rounded-md border px-3 text-sm"
    >
      {t("auth.google")}
    </button>
  );
}
```

`app/(auth)/signup/page.tsx` renders `<Suspense><SignupForm /></Suspense>` with the Google button
and a link back to `/login?next=…`; `LoginForm` gains `<GoogleButton next={next} />` under an *or*
rule.

- [ ] **Step 4: The way back**

`app/auth/callback/route.ts` — outside `(auth)` because it is a route handler, not a page:

```ts
import { NextResponse, type NextRequest } from "next/server";
import { safeNext } from "@/lib/auth/next";
import { createClient } from "@/lib/supabase/server";

/** Where Supabase sends somebody back — from a confirmation email or from
 *  Google — with a one-time code, which becomes the session cookie here. */
export async function GET(request: NextRequest) {
  const { origin, searchParams } = request.nextUrl;
  const next = safeNext(searchParams.get("next"));
  const code = searchParams.get("code");
  if (code) {
    const { error } = await (await createClient()).auth.exchangeCodeForSession(code);
    if (!error) return NextResponse.redirect(`${origin}${next}`);
  }
  // Expired, already used, or opened in another browser from the one that asked.
  return NextResponse.redirect(
    `${origin}/login?error=link&next=${encodeURIComponent(next)}`,
  );
}
```

`LoginForm` shows `auth.linkFailed` when `?error=link` is present.

- [ ] **Step 5: The gate**

`proxy.ts`:

```ts
const PUBLIC_PATHS = ["/login", "/signup", "/auth", "/accept-invite"];
...
// Signed in already: go where the link was going, not to the root.
if (user && (pathname === "/login" || pathname === "/signup")) {
  const url = request.nextUrl.clone();
  const next = safeNext(request.nextUrl.searchParams.get("next"));
  const [path, query = ""] = next.split("?");
  url.pathname = path;
  url.search = query ? `?${query}` : "";
  return NextResponse.redirect(url);
}
```

and the signed-out redirect sets `next` to the path *with* its query (`${pathname}${search}`), so an
invitation's token survives the detour.

- [ ] **Step 6: Run the checks**

Run: `npm run check --workspace web`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/web/components/auth/SignupForm.tsx apps/web/components/auth/SignupForm.test.tsx apps/web/components/auth/GoogleButton.tsx "apps/web/app/(auth)/signup/page.tsx" apps/web/app/auth/callback/route.ts apps/web/proxy.ts apps/web/components/auth/LoginForm.tsx
git commit -m "feat(web): an account, confirmed by email or by Google, and next that survives"
```

---

## Task A5: A first workspace for an owner who has none

**Files:**
- Create: `apps/web/lib/slug.ts`, `apps/web/lib/api/joining.ts`,
  `apps/web/components/auth/CreateWorkspace.tsx`, `apps/web/app/(auth)/onboarding/page.tsx`
- Test: `apps/web/lib/slug.test.ts`, `apps/web/components/auth/CreateWorkspace.test.tsx`

`app/(auth)/onboarding` is a static segment, so it wins over `[tenant]` — the root page's existing
redirect to `/onboarding` starts working without a change.

- [ ] **Step 1: Write the failing tests**

`lib/slug.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { slugFrom } from "./slug";

describe("slugFrom", () => {
  it("makes an address out of a name", () => {
    expect(slugFrom("Pollux Motors")).toBe("pollux-motors");
    expect(slugFrom("  Al Futtaim & Sons, Dubai ")).toBe("al-futtaim-sons-dubai");
    expect(slugFrom("Citroën Café")).toBe("citroen-cafe");
  });
  it("leaves an Arabic name for the owner to spell", () => {
    expect(slugFrom("معرض بولكس")).toBe("");
  });
  it("stays inside the API's 60 characters", () => {
    expect(slugFrom("a".repeat(80))).toHaveLength(60);
  });
});
```

`components/auth/CreateWorkspace.test.tsx` (`@/lib/api/joining` and the router mocked):

- "suggests the address from the name until the owner edits it".
- "creates the workspace and opens its Team screen, where inviting starts" — submit calls
  `createWorkspace({ name: "Pollux Motors", slug: "pollux-motors", timezone: "Asia/Dubai",
  currency: "AED", locales: ["en", "ar"] })` and pushes `/pollux-motors/settings/team`.
- "shows the API's sentence when the address is taken" — a 409 `ApiError` renders its detail.

- [ ] **Step 2: Run them and see them fail**

Run: `npm run test --workspace web -- lib/slug.test.ts components/auth/CreateWorkspace.test.tsx`
Expected: FAIL.

- [ ] **Step 3: `slugFrom` and the two calls made outside a workspace**

`lib/slug.ts`:

```ts
/** A workspace address from its name — `^[a-z0-9][a-z0-9-]*$`, 60 at most, as
 *  the API requires. Empty when the name has no Latin letters to borrow. */
export function slugFrom(name: string): string {
  return name
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60)
    .replace(/-+$/, "");
}
```

`lib/api/joining.ts`:

```ts
import { createApiClient, unwrap } from "./client";
import type { components } from "./schema";

/** The two calls made before somebody belongs to a workspace, so they carry
 *  no X-Tenant-Id — the API resolves them from the token alone. */
const api = createApiClient();

export type Joined = components["schemas"]["JoinedOut"];

export async function acceptInvitation(token: string): Promise<Joined> {
  return unwrap(await api.POST("/v1/invites/accept", { body: { token } }));
}

export async function createWorkspace(
  body: components["schemas"]["TenantCreate"],
): Promise<components["schemas"]["TenantOut"]> {
  return unwrap(await api.POST("/v1/tenants", { body }));
}
```

- [ ] **Step 4: The screen**

`components/auth/CreateWorkspace.tsx` — name, address (auto from `slugFrom(name)` until touched,
with `onboarding.slugHint`), time zone (a `select` of `Asia/Dubai`, `Asia/Riyadh`, `Asia/Qatar`,
`Asia/Kuwait`, `Asia/Bahrain`, `Asia/Muscat`, `Africa/Cairo`, `Africa/Casablanca`), currency
(`AED` default, three letters), languages (checkboxes `en`, `ar`, `fr`; `en` and `ar` ticked). On
success `router.push(`/${tenant.slug}/settings/team`)` and `router.refresh()`. The page renders it.

- [ ] **Step 5: Run the checks**

Run: `npm run check --workspace web`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/web/lib/slug.ts apps/web/lib/slug.test.ts apps/web/lib/api/joining.ts apps/web/components/auth/CreateWorkspace.tsx apps/web/components/auth/CreateWorkspace.test.tsx "apps/web/app/(auth)/onboarding/page.tsx"
git commit -m "feat(web): a first workspace for an owner who has none"
```

---

## Task A6: Inviting from the Team screen

**Files:**
- Create: `apps/web/components/settings/InviteForm.tsx`
- Modify: `apps/web/components/settings/TeamSettings.tsx`, `apps/web/lib/api/hooks.ts`
- Test: `apps/web/components/settings/InviteForm.test.tsx`

- [ ] **Step 1: Write the failing test**

`components/settings/InviteForm.test.tsx` (`@/lib/api/hooks` mocked: `useMe` as an admin,
`useTeams` with Local and Export, `useInvite` resolving `{ token: "tok", expires_at, role }`):

- "offers no role above the inviter's own" — an admin sees owner absent and admin, manager, sales,
  viewer present; the API refuses the rest anyway.
- "makes a link out of the token" — after submit, the read-only field holds
  `http://localhost:3000/accept-invite?token=tok`.
- "sends it on WhatsApp" — the anchor's href is
  `https://wa.me/?text=` + the encoded `invite.message` and link.
- "sends the teams ticked" — `useInvite().mutate` receives `{ email, role: "sales",
  team_ids: [local] }`.
- "shows the API's sentence when it refuses" — a 403 `ApiError` detail renders in the alert.

- [ ] **Step 2: Run it and see it fail**

Run: `npm run test --workspace web -- components/settings/InviteForm.test.tsx`
Expected: FAIL.

- [ ] **Step 3: The hook**

`lib/api/hooks.ts`:

```ts
export type Invitation = components["schemas"]["InviteOut"];

/** A signed, expiring link for one email (routes/tenants.create_invite). */
export function useInvite() {
  const { api, tenantId, header } = useTenantApi();
  return useMutation({
    mutationFn: async (body: components["schemas"]["InviteCreate"]) =>
      unwrap(
        await api.POST("/v1/tenants/{tenant_id}/invites", {
          params: { header, path: { tenant_id: tenantId } },
          body,
        }),
      ),
  });
}
```

- [ ] **Step 4: The form**

`components/settings/InviteForm.tsx`. The decision-carrying parts:

```tsx
/** The API's order (core/permissions.ROLES). It refuses anything above the
 *  inviter anyway; this only stops the form offering what will be refused. */
const RANK = ["viewer", "sales", "marketer", "manager", "admin", "owner"];

const offered = ROLES.filter((role) => RANK.indexOf(role) <= RANK.indexOf(me.data?.role ?? "viewer"));
...
const link = invitation && `${window.location.origin}/accept-invite?token=${invitation.token}`;
const whatsapp = link && `https://wa.me/?text=${encodeURIComponent(`${t("invite.message")}\n${link}`)}`;
```

The link sits in a read-only input with *Copy link* (`navigator.clipboard.writeText`, then
*Copied*), *Send on WhatsApp* opens `whatsapp` in a new tab, and `invite.ready` is followed by the
expiry date formatted in the page's locale. `ROLES` is exported from `TeamSettings.tsx`, where the
Team screen's role select already defines it. `TeamSettings` renders `<InviteForm />` as its first
section, and its header comment loses "Invitations arrive with sign-in in S7".

- [ ] **Step 5: Run the checks**

Run: `npm run check --workspace web`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/web/components/settings/InviteForm.tsx apps/web/components/settings/InviteForm.test.tsx apps/web/components/settings/TeamSettings.tsx apps/web/lib/api/hooks.ts
git commit -m "feat(web): inviting from the Team screen, with a link to send on WhatsApp"
```

---

## Task A7: Accepting an invitation

**Files:**
- Create: `apps/web/lib/jwt.ts`, `apps/web/lib/invitation.ts`,
  `apps/web/components/auth/JoinInvitation.tsx`, `apps/web/app/(auth)/accept-invite/page.tsx`
- Modify: `apps/web/lib/auth/token.ts`
- Test: `apps/web/lib/invitation.test.ts`, `apps/web/components/auth/JoinInvitation.test.tsx`

- [ ] **Step 1: Write the failing tests**

`lib/invitation.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { readInvitation } from "./invitation";

const token = (claims: object) =>
  `h.${btoa(JSON.stringify(claims)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "")}.s`;

const NOW = Date.UTC(2026, 9, 1);
const valid = {
  kind: "invite",
  tenant_name: "Pollux Motors",
  role: "sales",
  email: "layla@pollux.test",
  exp: NOW / 1000 + 3600,
};

describe("readInvitation", () => {
  it("says who is invited, where, and as what", () => {
    expect(readInvitation(token(valid), NOW)).toEqual({
      workspace: "Pollux Motors",
      role: "sales",
      email: "layla@pollux.test",
      expiresAt: new Date(valid.exp * 1000),
      expired: false,
    });
  });
  it("knows an expired one", () => {
    expect(readInvitation(token({ ...valid, exp: NOW / 1000 - 1 }), NOW)?.expired).toBe(true);
  });
  it("is nothing for a sign-in token or garbage", () => {
    expect(readInvitation(token({ ...valid, kind: undefined }), NOW)).toBeNull();
    expect(readInvitation("not-a-token", NOW)).toBeNull();
  });
});
```

`components/auth/JoinInvitation.test.tsx` (`@/lib/auth/token`, `@/lib/api/joining` and the router
mocked):

- "shows a signed-out visitor both ways in, each keeping the invitation" — the create-account link is
  `/signup?email=layla%40pollux.test&next=%2Faccept-invite%3Ftoken%3D…` and the sign-in link carries
  the same `next` (under `DEV_AUTH` both go to `/dev-login?next=…`).
- "says whose invitation it is when somebody else is signed in" — renders `accept.forEmail`, the
  invited address, `accept.signedInAs` and the current one, and a sign-out button; no Join.
- "joins and opens the inbox" — Join calls `acceptInvitation(token)` and pushes
  `/pollux-motors/inbox`.
- "shows the API's sentence when joining is refused".
- "does not offer to join an expired invitation" — renders `accept.expired` only.

- [ ] **Step 2: Run them and see them fail**

Run: `npm run test --workspace web -- lib/invitation.test.ts components/auth/JoinInvitation.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Reading a token, and an invitation**

`lib/jwt.ts`:

```ts
/** A JWT's claims, read and NOT verified — for showing, never for deciding.
 *  The API verifies every token it is handed. */
export function readClaims(token: string): Record<string, unknown> | null {
  const part = token.split(".")[1];
  if (!part) return null;
  try {
    const json = atob(part.replace(/-/g, "+").replace(/_/g, "/"));
    const claims: unknown = JSON.parse(decodeURIComponent(escape(json)));
    return claims && typeof claims === "object" ? (claims as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}
```

`lib/invitation.ts`:

```ts
import { readClaims } from "./jwt";

export type Invitation = {
  workspace: string;
  role: string;
  email: string;
  expiresAt: Date;
  expired: boolean;
};

/** What an invitation link says, for the page that opens it. */
export function readInvitation(token: string, now = Date.now()): Invitation | null {
  const claims = readClaims(token);
  if (!claims || claims.kind !== "invite") return null;
  const { tenant_name: workspace, role, email, exp } = claims;
  if (typeof workspace !== "string" || typeof role !== "string") return null;
  if (typeof email !== "string" || typeof exp !== "number") return null;
  const expiresAt = new Date(exp * 1000);
  return { workspace, role, email, expiresAt, expired: expiresAt.getTime() <= now };
}
```

`lib/auth/token.ts` gains:

```ts
/** Who is signed in, by address — the dev token and Supabase's both carry it. */
export async function signedInEmail(): Promise<string | null> {
  const token = await getBrowserAccessToken();
  const email = token && readClaims(token)?.email;
  return typeof email === "string" ? email.toLowerCase() : null;
}
```

- [ ] **Step 4: The screen**

`components/auth/JoinInvitation.tsx` — `{ token }` in, states in order: not an invitation
(`accept.invalid`), expired (`accept.expired`), loading who is signed in, signed out, somebody else,
ready. The decision-carrying parts:

```tsx
const invitation = readInvitation(token);
const back = `/accept-invite?token=${encodeURIComponent(token)}`;
const create = DEV_AUTH
  ? `/dev-login?next=${encodeURIComponent(back)}`
  : `/signup?email=${encodeURIComponent(invitation.email)}&next=${encodeURIComponent(back)}`;
const signIn = DEV_AUTH
  ? `/dev-login?next=${encodeURIComponent(back)}`
  : `/login?next=${encodeURIComponent(back)}`;
...
// The address is compared here only to say so kindly; the API is what refuses.
if (current && current !== invitation.email) return <Mismatch ... />;
...
async function join() {
  setBusy(true);
  try {
    const joined = await acceptInvitation(token);
    router.push(`/${joined.tenant_slug}/inbox`);
    router.refresh();
  } catch (e) {
    setError(e instanceof ApiError ? e.message : t("settings.saveFailed"));
    setBusy(false);
  }
}
```

Sign out: under `DEV_AUTH`, expire the `dev_token` cookie; otherwise
`createClient().auth.signOut()`; then reload the page. The ready state shows `accept.invitedTo`,
the workspace in bold, `accept.role` with the role's `role.*` label, and Join.
`app/(auth)/accept-invite/page.tsx` reads `token` with `useSearchParams` inside `Suspense` and
renders `<JoinInvitation token={token ?? ""} />`.

- [ ] **Step 5: Run the checks**

Run: `npm run check --workspace web`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/web/lib/jwt.ts apps/web/lib/invitation.ts apps/web/lib/invitation.test.ts apps/web/lib/auth/token.ts apps/web/components/auth/JoinInvitation.tsx apps/web/components/auth/JoinInvitation.test.tsx "apps/web/app/(auth)/accept-invite/page.tsx"
git commit -m "feat(web): accepting an invitation, and saying whose it is"
```

---

## Task A8: The whole check, then the joining path in a browser

**Files:**
- Modify: `docs/sales/plans/s7-pilot-readiness.md` (a Part A review)

- [ ] **Step 1: The whole check**

Stop the worker. Run: `npm run check && npm run check:openapi`
Expected: every suite green, the guards at 100%, no drift (the contract was regenerated in A1).

- [ ] **Step 2: The joining path, locally, in a browser**

`npm run db:seed`, the API, the worker and the web app. Write down what actually happens:

1. **Khalid** opens Settings → Team → *Invite someone*: `layla@pollux.test`, Sales, Local sales.
   The role list stops at his own; the link appears with its expiry; *Send on WhatsApp* opens a
   message holding it.
2. Signed out, the link opens the invitation — Pollux Motors, Sales — in Arabic after switching;
   both ways in keep the token.
3. *Somebody new* on the dev sign-in as `someone.else@pollux.test`: the invitation says it is for
   Layla and offers to sign out; `POST /v1/invites/accept` with that session is refused (403).
4. As `layla@pollux.test`, named Layla Hassan: Join lands in `/pollux-motors/inbox` as a
   salesperson — Local's unassigned James is there, Export's customers are not; the Team screen
   lists Layla Hassan with her address in Local sales; `psql` shows one membership, one
   `team_members` row, one profile.
5. The same link again: joining is idempotent — same role, no second membership.
6. *Somebody new* as `owner@newdealer.test` with no workspace: the root sends them to
   `/onboarding`; *New Dealer Motors* creates `new-dealer-motors` and opens its Team screen; the
   Team screen lists them as owner, by name.
7. `/login?next=//evil.example` after signing in lands on `/`.
8. Arabic at 375 px: every page of the path is usable, with no sideways scroll.

- [ ] **Step 3: The review, and commit**

Append `## Part A review — <date>` to this plan, in the shape of S6's: what the run found and where it
was fixed, what is sound as built, what is known and deliberately left, and the steps as verified.

```bash
git add docs/sales/plans/s7-pilot-readiness.md
git commit -m "docs(sales): S7 Part A, sign-in and joining, with the run recorded"
```

---

## Spec coverage (Part A)

| Requirement | Task |
|---|---|
| [08](../08-screens.md) §14 — email and password through Supabase Auth | A3, A4 |
| §14 — Google | A4 (the button and the callback); the provider is configured on the founder track and exercised in Part D |
| §14 — the invitation flow from DealerAI OS T1.2 | A1, A6, A7 |
| §14 — a first-run screen for an owner with no workspace | A5 |
| §14 — the error message never reveals whether an email exists | A3 (Supabase's sentence, unimproved), A4 (one answer to sign-up either way) |
| §14 done-when — an invited salesperson lands in the inbox with the right scope | A1 (role, teams, profile), A7, A8 step 4 |
| §14 done-when — a real sign-in works end to end | Part D, on staging: it needs the hosted Auth and the founder track's SMTP |
| [00](../00-prd.md) §7 S3 — a salesperson never sees another's customers | A1 keeps the visibility matrix green; A8 step 4 checks it on a joined rep |

---

## Execution

Inline in this session with `superpowers:executing-plans`, as S4 and S6 were — no subagents unless
asked. Checkpoints after Task A2 (the backend), Task A7 (the screens), and Task A8.
