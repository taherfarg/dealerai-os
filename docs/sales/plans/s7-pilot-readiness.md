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
their own, so it is five parts. Parts A, B and C are planned in full below. The rest follow this
project's convention from [09](../09-implementation-plan.md): each is written at pickup, appended to
this file under its own heading, with its own exit run.

| Part | What | Exit | Needs |
|---|---|---|---|
| **A** | Sign-in and joining ([08](../08-screens.md) §14) | An owner creates the workspace and invites a salesperson by a link; the salesperson joins with the invited email and lands in the inbox with the invited role and teams — in both languages, locally | — |
| **B** | Installable app and push ([07](../07-frontend.md) §8) | Installed on a phone; a customer assigned to a salesperson, or kept waiting, wakes that salesperson's phone | A |
| **C** | Arabic and accessibility pass ([08](../08-screens.md) §15.9) | Every screen reviewed in Arabic at 375 px and with a keyboard and a screen reader; the English the app itself writes into the Arabic UI — the items the S2, S4 and S6 reviews left — is gone. What the model writes for the team stays English, as S4 decided | — |
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

Added to `messages/en.ts` and `messages/ar.ts` (Tasks A3–A7 use them). The catalogue already has
`auth.signIn`, `auth.email`, `auth.password` and `auth.working` (Signing in…), from DealerAI OS;
they are reused.

| Key | English | Arabic |
|---|---|---|
| `auth.signInTitle` | Sign in to your workspace. | سجّل الدخول إلى مساحة عملك. |
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

---

## Part A review — 2026-09-30

Eight tasks, then the joining path in a browser against a freshly seeded workspace, with the
local sign-in standing in for Supabase Auth. The findings the plan fixed are in its table above;
these are what building it and running it found besides.

| Found | Why it mattered | Fixed in |
|---|---|---|
| The dev route opened its own database connection to write somebody new into `auth.users` | The import contract allows only modules that serve no request to open one — anything else could open one with no tenant context. The write lives in the local seed module, which already writes `auth.users` and refuses outside `ENV=local` | `0cd8032` |
| In dev mode the gate sent a signed-out visitor from an invitation straight to the dev sign-in | They never saw what they were invited to. `/accept-invite` is open in both gates | `0795600` |
| The password rule sat inside its label, so the field's name was "Password At least 8 characters" | A screen reader read the rule as the name. It is the field's description now | `0795600` |
| The plan's first-workspace form had separate time-zone and currency fields | Three answers to one question. One "where the showroom is" choice sets the country, the clock and the currency, with the browser's own country names in the page's language | `75d0c04` |

Sound as built, and left alone: the invitation's claims — one address, a role no higher than the
inviter's, this workspace's teams and its name; the refusal of a forwarded link (403 in the run);
the idempotent join (the same link again: 200, one membership); the profile written from what
somebody typed on sign-up; the root's redirect, which started working the moment `/onboarding`
existed; and the Arabic, which needed nothing beyond the catalogue.

Known and deliberately not changed in Part A:

- The real credential round trip — a Supabase password sign-in, an email confirmation, Google, and
  the production gate's handling of `next` (step 7 below) — needs the hosted Auth and the founder
  track's SMTP; it is Part D's, on staging. Locally the dev sign-in stands in, through the same
  pages.
- A salesperson's inbox opens on *Mine*, empty on their first day; their team's customers are one
  tab away, under *Unassigned*.
- An invitation cannot be revoked before it is used; it lasts seven days and works once, for one
  address.
- On a phone the settings sections are a scrolling row, so the last three sit off-screen until it is
  scrolled.

**Checks, final:** `npm run check` — 1,462 backend tests, the guards at 100% branch coverage, 194
web tests, types, lint and logical CSS; `npm run check:openapi` — no drift.

**Verified end to end on 2026-09-30**, with the API and the web app against a freshly seeded
workspace:

1. **Khalid** opened Settings → Team: *Invite someone* came first; as owner he was offered every
   role; `layla@pollux.test`, Sales, Local sales made a link valid "until 7 Oct 2026, 11:03" in
   Dubai time, with *Send on WhatsApp* holding it.
2. Signed out, the link showed "You are invited to join · Pollux Motors · Role: Sales" and, after
   switching, the same in Arabic, right to left; both ways in kept the token.
3. As `someone.else@pollux.test` through the local sign-in, the page came back to the invitation and
   said whose it was, offering only to sign out; the API refused that session with "this invitation
   is for another email address" (403).
4. Signed out from the page, then as `layla@pollux.test`, named Layla Hassan: Join landed in
   `/pollux-motors/inbox` as a salesperson with `own` scope — *Unassigned* held Local's James and
   nothing of Export's; the team view was refused, as it is for any salesperson. `psql`: one
   membership (sales), one `team_members` row (Local sales), one profile, "Layla Hassan
   <layla@pollux.test>"; Khalid's Team screen lists her by name in Local sales.
5. The same link again: 200, the same role, still one membership.
6. As `owner@newdealer.test`, named Hamad Al Nuaimi, with no workspace: the root sent them to
   `/onboarding`, in Arabic; *New Dealer Motors* suggested `new-dealer-motors` and opened its Team
   screen, *Invite someone* first, listing Hamad Al Nuaimi as owner.
7. `/login?next=//evil.example` — not reachable locally: dev mode passes a signed-in visitor
   straight through. `safeNext` and the sign-in form's redirect are unit-tested; the gate itself is
   Part D's.
8. Arabic at 375 px: the local sign-in, the invitation, the first workspace, sign-in, sign-up and the
   Team screen are right to left with no sideways scroll.

---

# Part B — Installable app and push

**Goal:** Ahmed adds DealerAI to his phone's Home Screen, turns notifications on once, and from then
on his phone tells him — with the app closed — that a customer was assigned to him, that one has
waited too long, that a task fell due, or that a lead turned hot; tapping it opens the right page.
With no network the app says so instead of showing a browser error. Nothing a customer said is ever
kept on the device by the service worker, and signing out silences the device.

**Architecture:** no push library and no new dependency. A notification row is still the one thing
that says "somebody should know": `notify()` queues `notification.push_requested` for the kinds that
earn a push, in the same transaction, and a worker handler sends it to every device its reader
subscribed. Sending is two RFCs over two libraries already installed — the payload encrypted per RFC
8291 (`aes128gcm`) with `cryptography`, the request signed per RFC 8292 (VAPID) with PyJWT — tested
byte for byte against RFC 8291's own worked example. A device belongs to whoever subscribed it
last. The one notification the product never wrote, a task falling due, is booked by a trigger on
`tasks`, the single place every way of writing a task passes through. In the browser, a small
service worker keeps one offline page and an icon — never an API response — shows what is pushed,
and opens the right page when it is tapped; the icons are code (`next/og`), not binaries.

**Tech stack:** Postgres 17 · FastAPI · `cryptography` · PyJWT · httpx · Next.js 16 (`app/manifest.ts`,
`next/og`) · the Push, Notifications and Service Worker APIs · Vitest · pytest.

**Before you start:**

- Docker Desktop running; `npm run db:up`. Stop the worker before running the suite; re-seed after.
- Read [07](../07-frontend.md) §8, [08](../08-screens.md) §13 (Notifications),
  [05](../05-workflows.md) §1 (`notification.push_requested`), [02](../02-data-model.md) §4.
- A service worker and push need a secure context. `localhost` is one; a phone on the LAN over plain
  HTTP is not — a push reaching a real phone is Part D's, on staging.

**Found while reading the code for this plan** — fixed in the tasks named:

| Found | Why it matters | Task |
|---|---|---|
| Nothing tells anybody a task fell due: there is no such notification | [07](../07-frontend.md) §8 pushes it; today a task goes red on a page nobody has open | B1, B2 |
| Tasks are written by the tasks API, the follow-up agent, the hand-over function and the seed | A due-time hook in one of them misses the others. A trigger on `tasks` is the one place they all pass | B1 |
| `notify()` cannot say whether it wrote a row | A push for a notification that was deduplicated away would be a second ping for one event | B4 |
| The worker will POST to whatever address a subscription names | A signed-in person could aim it at a host of their choosing. Only the push services browsers use are accepted | B5 |
| The gate's matcher covers `/manifest.webmanifest`, the icons, `/sw.js` and the offline page | A signed-out browser fetching the manifest is redirected to sign-in, and the app is not installable | B6 |
| Nothing stops a workspace being called `login`, `auth` — or now `icon` | The app's own page answers at that address, so the workspace can never be opened | B6 |
| The shell has no way to sign out | With push, a phone that changes hands keeps showing the last person's customers on its lock screen | B8 |

## What Part B does not build

| Item | Arrives with |
|---|---|
| Per-type preferences ("only waiting-too-long") | Phase 2, as [07](../07-frontend.md) §8 says |
| A push reaching a real phone | Part D: it needs HTTPS |
| Push for a customer's every message | Not among Phase 1's four: a busy rep's phone would never stop. It stays in the bell |
| Push for AI follow-ups and bulk hand-overs | They arrive in batches; the bell holds them |
| Notification text in the reader's language | Part C: every notification title is written in English by the backend today, pushed or not |
| A person in two workspaces hearing from both on one device | Later: a device's subscription belongs to one workspace, the one it was turned on in last |
| Caching pages or data for offline use | Never: the service worker holds no customer data, by design |

## File structure

| File | Responsibility |
|---|---|
| `supabase/migrations/0014_sales_push.sql` | **Create.** `push_subscriptions`, `app.remember_push_subscription()`, the `task_due` kind, the trigger that books a task's due time |
| `apps/api/src/dealerai/notifications/push.py` | **Create.** Encrypt (RFC 8291), sign (RFC 8292), send, and what an answer means for the device |
| `apps/api/src/dealerai/events/handlers/notify.py`, `handlers/__init__.py` | **Modify.** `PUSHED`; `notify()` queues the push; `notification.push_requested` |
| `apps/api/src/dealerai/events/handlers/crm.py` | **Modify.** `task.due_check` |
| `apps/api/src/dealerai/routes/push.py`, `main.py` | **Create / Modify.** The key, a device's subscription, the list, a test push |
| `apps/api/src/dealerai/routes/tenants.py` | **Modify.** Slugs the app itself answers at are taken |
| `apps/api/src/dealerai/config.py`, `.env.example` | **Modify.** `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT` |
| `apps/api/src/dealerai/scripts/vapid.py`, `package.json` | **Create / Modify.** `npm run vapid:keys` writes a key to `.env` without printing it |
| `apps/api/tests/conftest.py` | **Modify.** A push service that keeps what it was sent, and a phone that can open it |
| `apps/web/app/manifest.ts`, `app/icon.tsx`, `app/apple-icon.tsx` | **Create.** Installable, with icons drawn in code |
| `apps/web/public/sw.js`, `public/offline.html` | **Create.** The service worker and its one page |
| `apps/web/proxy.ts` | **Modify.** The manifest, icons, worker and offline page pass the gate |
| `apps/web/components/ServiceWorker.tsx`, `app/layout.tsx` | **Create / Modify.** Registering the worker; keeping the browser's offer to install |
| `apps/web/lib/push.ts` | **Create.** What this browser can do, subscribing it, naming a device |
| `apps/web/components/settings/NotificationSettings.tsx`, `sections.ts`, `app/[tenant]/settings/notifications/page.tsx`, `lib/api/{hooks,keys}.ts` | **Create / Modify.** Settings → Notifications |
| `apps/web/lib/auth/sign-out.ts`, `components/SignOutButton.tsx`, `components/Shell.tsx`, `components/auth/JoinInvitation.tsx` | **Create / Modify.** Signing out, which silences the device first |
| `apps/web/messages/{en,ar}.ts` | **Modify.** Every string Part B shows |

---

## Task B1: Where a push goes, and a task that books its own due time

**Files:**
- Create: `supabase/migrations/0014_sales_push.sql`
- Test: `apps/api/tests/test_push_schema.py`, `apps/api/tests/test_task_due.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_push_schema.py`:

```python
"""Where a push goes: a device somebody subscribed, theirs and nobody else's."""

from __future__ import annotations

import uuid

from conftest import SALES_1, SALES_2, TENANT_A, reseed_with_people
from dealerai.db.session import tenant_session

ENDPOINT = "https://fcm.googleapis.com/fcm/send/abc"


async def _subscribe(user: uuid.UUID, endpoint: str = ENDPOINT) -> uuid.UUID:
    async with tenant_session(TENANT_A, user_id=user, scope="own") as conn:
        return await conn.fetchval(  # type: ignore[no-any-return]
            "select app.remember_push_subscription($1, $2, $3, 'p256dh', 'auth', 'Chrome')",
            TENANT_A,
            user,
            endpoint,
        )


async def _count(user: uuid.UUID | None) -> int:
    async with tenant_session(TENANT_A, user_id=user, scope="own") as conn:
        return await conn.fetchval("select count(*) from push_subscriptions")  # type: ignore[no-any-return]


async def test_a_device_is_its_owners_and_nobody_elses(db: None) -> None:
    await reseed_with_people()
    await _subscribe(SALES_1)
    assert await _count(SALES_1) == 1
    assert await _count(SALES_2) == 0
    # The worker has no user in its session: it reads everybody's, to send.
    assert await _count(None) == 1


async def test_a_device_belongs_to_whoever_subscribed_it_last(db: None) -> None:
    """A shared phone that changes hands must not keep telling the last person."""
    await reseed_with_people()
    await _subscribe(SALES_1)
    await _subscribe(SALES_2)
    async with tenant_session(TENANT_A) as conn:
        owners = [r["user_id"] for r in await conn.fetch("select user_id from push_subscriptions")]
    assert owners == [SALES_2]


async def test_one_person_may_have_several_devices(db: None) -> None:
    await reseed_with_people()
    await _subscribe(SALES_1)
    await _subscribe(SALES_1, f"{ENDPOINT}-laptop")
    assert await _count(SALES_1) == 2
```

`tests/test_task_due.py` — the trigger now; Task B2 adds the handler's tests to the same file:

```python
"""A task falling due: booked by the task itself, told to its assignee once."""

from __future__ import annotations

import json
import uuid
from datetime import timedelta

import asyncpg

from conftest import SALES_1, TENANT_A, reseed_with_people
from dealerai.events.bus import Event


async def _task(
    su: asyncpg.Connection,
    *,
    due_in: timedelta = timedelta(hours=1),
    status: str = "open",
    source: str = "human",
) -> uuid.UUID:
    return await su.fetchval(  # type: ignore[no-any-return]
        """insert into tasks (tenant_id, title, due_at, status, source, assignee_id, created_by)
           values ($1, 'Call Omar', now() + $2::interval, $3, $4, $5, $5) returning id""",
        TENANT_A,
        due_in,
        status,
        source,
        SALES_1,
    )


async def _booked(su: asyncpg.Connection, task: uuid.UUID) -> list[Event]:
    """The checks a task booked for itself, as the worker would claim them."""
    rows = await su.fetch(
        """select id, tenant_id, event_type, payload, dedupe_key from events
            where event_type = 'task.due_check' and payload->>'task_id' = $1 order by id""",
        str(task),
    )
    return [
        Event(
            id=r["id"],
            tenant_id=r["tenant_id"],
            event_type=r["event_type"],
            payload=json.loads(r["payload"]),
            attempts=1,
            dedupe_key=r["dedupe_key"],
        )
        for r in rows
    ]


async def test_a_task_books_a_check_at_its_due_time(db: None, su: asyncpg.Connection) -> None:
    await reseed_with_people()
    task = await _task(su)
    assert len(await _booked(su, task)) == 1
    assert await su.fetchval(
        """select e.run_after = t.due_at and e.status = 'pending' and e.tenant_id = t.tenant_id
             from events e join tasks t on t.id = $1
            where e.event_type = 'task.due_check'""",
        task,
    )


async def test_moving_a_task_books_the_new_time(db: None, su: asyncpg.Connection) -> None:
    await reseed_with_people()
    task = await _task(su)
    await su.execute("update tasks set due_at = due_at + interval '1 day' where id = $1", task)
    assert len(await _booked(su, task)) == 2


async def test_renaming_a_task_books_nothing_new(db: None, su: asyncpg.Connection) -> None:
    await reseed_with_people()
    task = await _task(su)
    await su.execute("update tasks set title = 'Call Omar today' where id = $1", task)
    assert len(await _booked(su, task)) == 1


async def test_a_task_that_is_done_or_the_ais_books_nothing(
    db: None, su: asyncpg.Connection
) -> None:
    await reseed_with_people()
    assert await _booked(su, await _task(su, status="done")) == []
    # An AI follow-up is due at once and already announces itself (followup_ready).
    assert await _booked(su, await _task(su, source="ai")) == []


async def test_a_task_falling_due_is_a_kind_of_notification(
    db: None, su: asyncpg.Connection
) -> None:
    await reseed_with_people()
    await su.execute(
        """insert into notifications (tenant_id, user_id, kind, title)
           values ($1, $2, 'task_due', 'Call Omar')""",
        TENANT_A,
        SALES_1,
    )
```

- [ ] **Step 2: Run them and see them fail**

Run: `cd apps/api && uv run pytest tests/test_push_schema.py tests/test_task_due.py -q`
Expected: FAIL — `function app.remember_push_subscription … does not exist`, no `task.due_check`
events, and the `task_due` kind violates `notifications_kind_check`.

- [ ] **Step 3: The migration**

`supabase/migrations/0014_sales_push.sql`:

```sql
-- =============================================================================
-- 0014_sales_push — S7 Part B: a notification that reaches a phone.
-- Where a push goes (a device somebody subscribed), and the one notification
-- the product never wrote: a task falling due. See docs/sales/07-frontend.md
-- § 8 and docs/sales/02-data-model.md § 4.
-- =============================================================================

create table push_subscriptions (
  id              uuid primary key default gen_random_uuid(),
  tenant_id       uuid not null references tenants(id) on delete cascade,
  user_id         uuid not null references auth.users(id) on delete cascade,
  -- The push service's address for one browser on one device.
  -- ponytail: unique across workspaces, so somebody in two of them hears from
  -- the one this device was turned on in last. Make it (tenant_id, endpoint)
  -- when a second tenant shares people with the first.
  endpoint        text not null unique,
  p256dh          text not null,
  auth            text not null,
  user_agent      text,
  failure_count   int not null default 0,
  last_success_at timestamptz,
  created_at      timestamptz not null default now()
);
create index on push_subscriptions (tenant_id, user_id);

-- The caller's own devices, never a colleague's. The worker has no user in its
-- session and reads everybody's, to send — as with notifications (0008).
alter table push_subscriptions enable row level security;
alter table push_subscriptions force row level security;
create policy own_rows on push_subscriptions
  using (app.has_tenant_access(tenant_id)
         and (user_id = (select app.current_user_id())
              or (select app.current_user_id()) is null))
  with check (app.has_tenant_access(tenant_id));
revoke all on push_subscriptions from anon, authenticated;

-- A device belongs to whoever subscribed it last: a shared phone that changes
-- hands must not keep telling the last person. The row it replaces may be
-- somebody else's, which the caller cannot see — hence definer.
create or replace function app.remember_push_subscription(
    p_tenant     uuid,
    p_user       uuid,
    p_endpoint   text,
    p_p256dh     text,
    p_auth       text,
    p_user_agent text
)
returns uuid
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    subscription uuid;
begin
    delete from push_subscriptions where endpoint = p_endpoint;
    insert into push_subscriptions (tenant_id, user_id, endpoint, p256dh, auth, user_agent)
    values (p_tenant, p_user, p_endpoint, p_p256dh, p_auth, p_user_agent)
    returning id into subscription;
    return subscription;
end;
$$;

revoke all on function app.remember_push_subscription(uuid, uuid, text, text, text, text)
    from public;
grant execute on function app.remember_push_subscription(uuid, uuid, text, text, text, text)
    to dealerai_app;

-- A task falling due tells its assignee: one more kind for the bell, and the
-- push that follows it.
alter table notifications drop constraint notifications_kind_check;
alter table notifications add constraint notifications_kind_check check (kind in
  ('message_received', 'assigned', 'waiting_due_soon', 'waiting_missed',
   'unassigned_waiting', 'template_rejected', 'channel_disconnected',
   'channel_quality', 'contact_assigned', 'lead_hot', 'followup_ready',
   'ai_budget_exhausted', 'brief_ready', 'task_due'));

-- Every way a task is written — the tasks API, a hand-over, the seed — passes
-- here, so here is where its due time is booked: a check at that moment, which
-- does nothing if the task was done, cancelled or moved by then
-- (events/handlers/crm.py). An AI follow-up is due at once and already
-- announces itself (followup_ready). A task changing hands books nothing: the
-- check reads whose it is when it runs.
create or replace function app.book_task_due()
returns trigger
language plpgsql
set search_path = public, pg_temp
as $$
begin
    if new.status = 'open' and new.source <> 'ai' then
        insert into events (tenant_id, event_type, payload, dedupe_key, priority, run_after)
        values (new.tenant_id, 'task.due_check',
                jsonb_build_object('task_id', new.id, 'due_at', new.due_at),
                'task-due:' || new.id || ':' || extract(epoch from new.due_at)::bigint,
                5, new.due_at)
        on conflict do nothing;
    end if;
    return null;
end;
$$;

revoke all on function app.book_task_due() from public;

create trigger tasks_book_due after insert or update of due_at, status on tasks
  for each row execute function app.book_task_due();
```

- [ ] **Step 4: Run them and see them pass**

Run: `cd apps/api && uv run pytest tests/test_push_schema.py tests/test_task_due.py tests/test_visibility.py tests/test_tasks_api.py tests/test_followups.py tests/test_seed_sales.py -q`
Expected: PASS. A test that counted *every* event after writing a task now sees one more
(`task.due_check`): narrow its query to the type it is about rather than loosening the count.

- [ ] **Step 5: Commit**

```bash
git add supabase/migrations/0014_sales_push.sql apps/api/tests/test_push_schema.py apps/api/tests/test_task_due.py
git commit -m "feat(sales): where a push goes, and a task that books its own due time"
```

---

## Task B2: A task falls due, and its assignee hears

**Files:**
- Modify: `apps/api/src/dealerai/events/handlers/crm.py`, `docs/sales/05-workflows.md` (the catalogue)
- Test: `apps/api/tests/test_task_due.py`

- [ ] **Step 1: Write the failing tests**

Appended to `tests/test_task_due.py` (`from dealerai.events.handlers import crm` joins the imports).
Each hands the handler the event the trigger really booked, so the payload's shape is the
database's, not the test's:

```python
async def _told(su: asyncpg.Connection) -> list[asyncpg.Record]:
    return await su.fetch(  # type: ignore[no-any-return]
        "select user_id, kind, title, body, href from notifications where kind = 'task_due'"
    )


async def test_the_assignee_is_told_once(db: None, su: asyncpg.Connection) -> None:
    await reseed_with_people()
    task = await _task(su)
    contact = await su.fetchval(
        "insert into contacts (tenant_id, full_name) values ($1, 'Omar Haddad') returning id",
        TENANT_A,
    )
    await su.execute("update tasks set contact_id = $2 where id = $1", task, contact)
    [event] = await _booked(su, task)

    await crm.on_task_due(event)
    await crm.on_task_due(event)  # the queue retries

    [told] = await _told(su)
    assert told["user_id"] == SALES_1
    assert (told["title"], told["body"], told["href"]) == ("Due now: Call Omar", "Omar Haddad", "/tasks")


async def test_a_task_done_by_then_tells_nobody(db: None, su: asyncpg.Connection) -> None:
    await reseed_with_people()
    task = await _task(su)
    [event] = await _booked(su, task)
    await su.execute("update tasks set status = 'done' where id = $1", task)

    await crm.on_task_due(event)

    assert await _told(su) == []


async def test_a_task_moved_by_then_waits_for_its_new_time(
    db: None, su: asyncpg.Connection
) -> None:
    await reseed_with_people()
    task = await _task(su)
    await su.execute("update tasks set due_at = due_at + interval '1 day' where id = $1", task)
    old, new = await _booked(su, task)

    await crm.on_task_due(old)
    assert await _told(su) == []

    await crm.on_task_due(new)
    assert len(await _told(su)) == 1


async def test_a_task_deleted_by_then_is_not_an_error(db: None, su: asyncpg.Connection) -> None:
    await reseed_with_people()
    task = await _task(su)
    [event] = await _booked(su, task)
    await su.execute("delete from tasks where id = $1", task)

    await crm.on_task_due(event)

    assert await _told(su) == []
```

- [ ] **Step 2: Run them and see them fail**

Run: `cd apps/api && uv run pytest tests/test_task_due.py -q`
Expected: FAIL — `module 'dealerai.events.handlers.crm' has no attribute 'on_task_due'`.

- [ ] **Step 3: The handler**

In `events/handlers/crm.py` — the module's first line becomes `"""The CRM's side of the queue:
telling somebody a customer is theirs now, or that a task of theirs fell due."""`, and
`from datetime import datetime` joins the imports:

```python
@handler("task.due_check")
async def on_task_due(event: Event) -> None:
    """A task's due time came: tell its assignee — unless it was done,
    cancelled or moved since the trigger booked this (migration 0014)."""
    if event.tenant_id is None:
        raise ValueError("task.due_check requires a tenant")
    task_id = UUID(str(event.payload["task_id"]))
    booked = datetime.fromisoformat(str(event.payload["due_at"]))

    async with tenant_session(event.tenant_id) as conn:
        task = await conn.fetchrow(
            """select t.title, t.assignee_id, t.due_at, t.status, c.full_name
                 from tasks t left join contacts c on c.id = t.contact_id
                where t.id = $1""",
            task_id,
        )
        if task is None or task["status"] != "open" or task["due_at"] != booked:
            return
        await notify(
            conn,
            tenant_id=event.tenant_id,
            user_id=task["assignee_id"],
            kind="task_due",
            title=f"Due now: {task['title']}",
            body=task["full_name"],
            entity={"type": "task", "id": str(task_id)},
            # Re-opening a task after its time re-books the check; it is still
            # one piece of news.
            dedupe_key=f"task-due:{task_id}:{booked.isoformat()}",
        )
```

`docs/sales/05-workflows.md` §1 gains a row for `task.due_check` — emitted by the `tasks_book_due`
trigger at the task's due time, priority 5, handled by `crm.on_task_due`.

- [ ] **Step 4: Run them and see them pass**

Run: `cd apps/api && uv run pytest tests/test_task_due.py tests/test_crm_events.py tests/test_import_contracts.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/dealerai/events/handlers/crm.py apps/api/tests/test_task_due.py docs/sales/05-workflows.md
git commit -m "feat(sales): a task falls due, and its assignee hears"
```

---

## Task B3: A push, encrypted and signed

**Files:**
- Create: `apps/api/src/dealerai/notifications/__init__.py` (empty),
  `apps/api/src/dealerai/notifications/push.py`
- Test: `apps/api/tests/test_push_crypto.py`

- [ ] **Step 1: Write the failing tests** — RFC 8291 Appendix A, whole

`tests/test_push_crypto.py`:

```python
"""Web Push, checked against the standards rather than against itself."""

from __future__ import annotations

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from dealerai.notifications import push

# RFC 8291, Appendix A — every value as printed there.
PLAINTEXT = b"When I grow up, I want to be a watermelon"
AS_PRIVATE = "yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"
UA_PUBLIC = (
    "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcx"
    "aOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4"
)
AUTH_SECRET = "BTBZMqHH6r4Tts7J_aSIgg"
SALT = "DGv6ra1nlYgDCS1FRnbzlw"
HEADER = (
    "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27ml"
    "mlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A8"
)
CIPHERTEXT = "8pfeW0KbunFT06SuDKoJH9Ql87S1QUrdirN6GcG7sFz1y1sqLgVi1VhjVkHsUoEsbI_0LpXMuGvnzQ"
# RFC 8291, Section 5 — the whole message as it goes on the wire.
MESSAGE = (
    "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27ml"
    "mlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A_yl95bQpu6cVPT"
    "pK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN"
)


def test_the_rfcs_own_example_comes_out_byte_for_byte() -> None:
    body = push.encrypt(
        PLAINTEXT,
        p256dh=UA_PUBLIC,
        auth=AUTH_SECRET,
        salt=push.unb64(SALT),
        server_key=push.private_key(AS_PRIVATE),
    )
    assert body == push.unb64(HEADER) + push.unb64(CIPHERTEXT)
    assert push.b64(body) == MESSAGE


def test_two_messages_to_one_device_share_nothing() -> None:
    """A fresh key and salt each time: the same words never look the same twice."""
    first = push.encrypt(PLAINTEXT, p256dh=UA_PUBLIC, auth=AUTH_SECRET)
    second = push.encrypt(PLAINTEXT, p256dh=UA_PUBLIC, auth=AUTH_SECRET)
    assert first[:16] != second[:16] and first[21:86] != second[21:86]


def test_the_request_is_signed_for_the_push_service_it_goes_to() -> None:
    key = ec.generate_private_key(ec.SECP256R1())
    scalar = push.b64(key.private_numbers().private_value.to_bytes(32, "big"))
    header = push.vapid(
        "https://fcm.googleapis.com/fcm/send/abc", private=scalar, subject="mailto:ops@pollux.test"
    )
    scheme, _, rest = header.partition(" ")
    fields = dict(part.strip().split("=", 1) for part in rest.split(","))
    assert scheme == "vapid" and fields["k"] == push.public_key(scalar)
    claims = jwt.decode(
        fields["t"], key.public_key(), algorithms=["ES256"], audience="https://fcm.googleapis.com"
    )
    assert claims["sub"] == "mailto:ops@pollux.test"
    assert 0 < claims["exp"] - claims["iat"] <= 24 * 3600, "push services refuse a longer one"


def test_a_long_notification_still_fits_the_one_record() -> None:
    payload = push.message("ع" * 500, "ب" * 5000, href="/pollux-motors/inbox/x", tag="assigned")
    assert len(push.encrypt(payload, p256dh=UA_PUBLIC, auth=AUTH_SECRET)) <= push.RECORD_SIZE


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://fcm.googleapis.com/fcm/send/abc",
        "https://updates.push.services.mozilla.com/wpush/v2/abc",
        "https://web.push.apple.com/abc",
        "https://wns2-par02p.notify.windows.com/w/?token=abc",
    ],
)
def test_the_push_services_browsers_use_are_accepted(endpoint: str) -> None:
    assert push.is_push_service(endpoint)


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://localhost:8000/v1/tenants",
        "https://10.0.0.5/internal",
        "http://fcm.googleapis.com/fcm/send/abc",
        "https://fcm.googleapis.com.evil.example/abc",
        "https://evilfcm.googleapis.com.example/abc",
        "not a url",
    ],
)
def test_nobody_aims_the_worker_at_a_host_of_their_choosing(endpoint: str) -> None:
    assert not push.is_push_service(endpoint)
```

- [ ] **Step 2: Run them and see them fail**

Run: `cd apps/api && uv run pytest tests/test_push_crypto.py -q`
Expected: FAIL — `No module named 'dealerai.notifications'`.

- [ ] **Step 3: The module**

`src/dealerai/notifications/push.py`:

```python
"""Web Push, from the worker (docs/sales/07-frontend.md § 8).

Two standards over two libraries the API already has, rather than a push
library: the payload is encrypted per RFC 8291 (aes128gcm) with `cryptography`,
and the request is signed per RFC 8292 (VAPID) with PyJWT.
tests/test_push_crypto.py checks the first against the RFC's own worked
example, byte for byte.
"""

from __future__ import annotations

import base64
import json
import os
import time
from urllib.parse import urlsplit

import jwt
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

#: A push service must take 4096 octets and need not take more. Everything sent
#: here is one record, well inside it — message() sees to that.
RECORD_SIZE = 4096
#: A VAPID token's life. Push services refuse more than a day.
VAPID_SECONDS = 12 * 3600

#: The push services browsers use. The worker POSTs to a subscription's
#: endpoint, so an address that is none of these is refused when it is offered:
#: nobody gets to aim the worker at a host of their choosing.
PUSH_SERVICES = (
    "fcm.googleapis.com",  # Chrome, and every browser on Android
    "updates.push.services.mozilla.com",  # Firefox
    "web.push.apple.com",  # Safari, and every browser on an iPhone
    "notify.windows.com",  # Edge on Windows
)


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def is_push_service(endpoint: str) -> bool:
    target = urlsplit(endpoint)
    host = target.hostname or ""
    return target.scheme == "https" and any(
        host == known or host.endswith(f".{known}") for known in PUSH_SERVICES
    )


def private_key(scalar: str) -> ec.EllipticCurvePrivateKey:
    """A P-256 key from its base64url scalar — the form VAPID_PRIVATE_KEY takes."""
    return ec.derive_private_key(int.from_bytes(unb64(scalar), "big"), ec.SECP256R1())


def _point(key: ec.EllipticCurvePrivateKey) -> bytes:
    return key.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)


def public_key(scalar: str) -> str:
    """What the browser subscribes with: the uncompressed point, base64url."""
    return b64(_point(private_key(scalar)))


def hkdf(*, salt: bytes, ikm: bytes, info: bytes, length: int) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(ikm)


def encrypt(
    plaintext: bytes,
    *,
    p256dh: str,
    auth: str,
    salt: bytes | None = None,
    server_key: ec.EllipticCurvePrivateKey | None = None,
) -> bytes:
    """RFC 8291: one aes128gcm record only this subscription can open.

    `salt` and `server_key` are fresh for every message; they are parameters so
    the RFC's example, which fixes both, can be reproduced.
    """
    ua_public = unb64(p256dh)
    salt = salt or os.urandom(16)
    server_key = server_key or ec.generate_private_key(ec.SECP256R1())
    as_public = _point(server_key)

    shared = server_key.exchange(
        ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public)
    )
    ikm = hkdf(
        salt=unb64(auth),
        ikm=shared,
        info=b"WebPush: info\x00" + ua_public + as_public,
        length=32,
    )
    key = hkdf(salt=salt, ikm=ikm, info=b"Content-Encoding: aes128gcm\x00", length=16)
    nonce = hkdf(salt=salt, ikm=ikm, info=b"Content-Encoding: nonce\x00", length=12)
    # 0x02 ends the last — here the only — record.
    ciphertext = AESGCM(key).encrypt(nonce, plaintext + b"\x02", None)
    header = salt + RECORD_SIZE.to_bytes(4, "big") + bytes([len(as_public)]) + as_public
    return header + ciphertext


def vapid(endpoint: str, *, private: str, subject: str) -> str:
    """RFC 8292: who is sending, signed for the push service it is sent to."""
    target = urlsplit(endpoint)
    now = int(time.time())
    token = jwt.encode(
        {
            "aud": f"{target.scheme}://{target.netloc}",
            "iat": now,
            "exp": now + VAPID_SECONDS,
            "sub": subject,
        },
        private_key(private),
        algorithm="ES256",
    )
    return f"vapid t={token}, k={public_key(private)}"


def message(title: str, body: str | None, *, href: str, tag: str) -> bytes:
    """What the service worker shows (apps/web/public/sw.js reads these names).

    Cut to what a lock screen shows anyway, which also keeps every message
    inside the one record encrypt() writes.
    """
    return json.dumps(
        {"title": title[:120], "body": (body or "")[:300], "href": href, "tag": tag},
        ensure_ascii=False,
    ).encode()
```

- [ ] **Step 4: Run them and see them pass**

Run: `cd apps/api && uv run pytest tests/test_push_crypto.py -q && uv run mypy src/dealerai/notifications`
Expected: PASS. If the first test fails, compare against the RFC's intermediate values in order —
`ecdh_secret` `kyrL1jIIOHEzg3sM2ZWRHDRB62YACZhhSlknJ672kSs`, IKM
`S4lYMb_L0FxCeq0WhDx813KgSYqU26kOyzWUdsXYyrg`, CEK `oIhVW04MRdy2XN9CiKLxTg`, NONCE
`4h_95klXJ5E_qnoN` — to find the step that differs.

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/dealerai/notifications apps/api/tests/test_push_crypto.py
git commit -m "feat(sales): a push, encrypted and signed, to the letter of two RFCs"
```

---

## Task B4: The notification, on every device its reader subscribed

**Files:**
- Modify: `apps/api/src/dealerai/config.py`, `apps/api/src/dealerai/notifications/push.py`,
  `apps/api/src/dealerai/events/handlers/notify.py`, `apps/api/src/dealerai/events/handlers/__init__.py`,
  `apps/api/tests/conftest.py`
- Test: `apps/api/tests/test_push_delivery.py`

- [ ] **Step 1: Settings**

`config.py`, after the WhatsApp settings:

```python
    #: Web Push (docs/sales/07-frontend.md § 8). The private key is a base64url
    #: P-256 scalar — `npm run vapid:keys` writes one locally. Unset, nothing is
    #: pushed and the bell works as before. The subject is who a push service
    #: writes to about this sender: a real mailto: or https: address in
    #: production, where Apple refuses a made-up one.
    vapid_private_key: str | None = None
    vapid_subject: str = "mailto:push@dealerai.local"
```

- [ ] **Step 2: A push service for the tests, and a phone that can open what it gets**

`tests/conftest.py` gains (imports: `httpx`, `ec` and `AESGCM` from `cryptography`,
`dealerai.notifications.push`):

```python
# --------------------------------------------------------------------------
# web push: a push service that keeps what it was sent, and a phone to open it
# --------------------------------------------------------------------------

#: RFC 8291 Appendix A's user agent — a device whose private key is known, so a
#: test can open what was sent to it, as a browser would.
PHONE = {
    "endpoint": "https://fcm.googleapis.com/fcm/send/the-phone",
    "p256dh": (
        "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcx"
        "aOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4"
    ),
    "auth": "BTBZMqHH6r4Tts7J_aSIgg",
}
PHONE_PRIVATE = "q1dXpw3UpT5VOmu_cf_v6ih07Aems3njxI-JWgLcM94"


def open_push(body: bytes) -> dict[str, str]:
    """What the browser does with a push (RFC 8291 § 4), with the phone's key."""
    salt, as_public, ciphertext = body[:16], body[21:86], body[86:]
    shared = push.private_key(PHONE_PRIVATE).exchange(
        ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_public)
    )
    ikm = push.hkdf(
        salt=push.unb64(PHONE["auth"]),
        ikm=shared,
        info=b"WebPush: info\x00" + push.unb64(PHONE["p256dh"]) + as_public,
        length=32,
    )
    key = push.hkdf(salt=salt, ikm=ikm, info=b"Content-Encoding: aes128gcm\x00", length=16)
    nonce = push.hkdf(salt=salt, ikm=ikm, info=b"Content-Encoding: nonce\x00", length=12)
    opened = AESGCM(key).decrypt(nonce, ciphertext, None)
    assert opened.endswith(b"\x02"), "the last record ends with 0x02"
    return json.loads(opened[:-1])  # type: ignore[no-any-return]


class PushService:
    """Answers as a push service would, and keeps what it was sent."""

    def __init__(self) -> None:
        self.status = 201
        self.requests: list[httpx.Request] = []

    def client(self) -> httpx.AsyncClient:
        def answer(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return httpx.Response(self.status)

        return httpx.AsyncClient(transport=httpx.MockTransport(answer))


@pytest.fixture
def push_service(monkeypatch: pytest.MonkeyPatch) -> PushService:
    """Push configured with a key made for this test, and nothing leaving the machine."""
    key = ec.generate_private_key(ec.SECP256R1())
    scalar = push.b64(key.private_numbers().private_value.to_bytes(32, "big"))
    monkeypatch.setattr(get_settings(), "vapid_private_key", scalar)
    service = PushService()
    monkeypatch.setattr(push, "client", service.client)
    return service
```

- [ ] **Step 3: Write the failing tests**

`tests/test_push_delivery.py`. Helpers: `_device(su, user=SALES_1, endpoint=PHONE["endpoint"])`
inserts a `push_subscriptions` row with the phone's keys; `_tell(kind="assigned", dedupe="a")` calls
`notify()` in a worker session for SALES_1 — title "A customer is waiting for you", body "Omar
Haddad", a conversation entity; `_requested(su)` returns the queued `notification.push_requested`
events as `Event`s.

- `test_a_notification_worth_a_push_asks_for_one_once` — `_tell()` twice with one dedupe key: one
  notification, one event, priority 8, its payload the notification's id.
- `test_the_rest_stay_in_the_bell` — `_tell(kind="brief_ready")` and `_tell(kind="message_received")`:
  two notifications, no push event.
- `test_the_device_gets_what_was_said_sealed_for_it` — a device, `_tell()`, the handler: one request
  to the phone's endpoint; `open_push(request.content)` is `{"title": "A customer is waiting for
  you", "body": "Omar Haddad", "href": "/alpha/inbox/<id>", "tag": "assigned"}`; the headers carry
  `Content-Encoding: aes128gcm`, `TTL`, `Urgency: high` and an `Authorization` starting `vapid t=`;
  `last_success_at` is set.
- `test_a_device_that_is_gone_is_forgotten` — parametrised 404 and 410: the row is deleted.
- `test_a_push_service_having_a_bad_day_is_counted_not_forgotten` — 500: the row stays,
  `failure_count` 1; a 201 afterwards puts it back to 0.
- `test_a_push_service_that_cannot_be_reached_fails_nothing` — the transport raises
  `httpx.ConnectError`: the handler returns, `failure_count` 1.
- `test_with_no_key_nothing_is_sent_and_nothing_fails` — `vapid_private_key` None: no request.
- `test_only_its_readers_devices_hear` — a device of SALES_2 beside SALES_1's: one request.
- `test_a_notification_read_away_by_then_is_not_an_error` — the notification row deleted before the
  handler runs: it returns.

- [ ] **Step 4: Run them and see them fail**

Run: `cd apps/api && uv run pytest tests/test_push_delivery.py -q`
Expected: FAIL — no push event is queued; `notify.on_push_requested` does not exist.

- [ ] **Step 5: Sending, and what an answer means**

`notifications/push.py` gains (imports: `Sequence` and `Mapping` from `collections.abc`, `Any`,
`UUID`, `asyncpg`, `httpx`, `structlog`; `log = structlog.get_logger()`):

```python
#: How long a push service keeps trying a phone that is off. An hour: "a
#: customer is waiting" from this morning is not news this afternoon.
TTL_SECONDS = 3600


def client() -> httpx.AsyncClient:
    """Its own function so a test can hand the sender a push service of its own."""
    return httpx.AsyncClient(timeout=10)


async def send(
    http: httpx.AsyncClient, device: Mapping[str, Any], payload: bytes, *, private: str, subject: str
) -> int:
    """One push to one device: the push service's status, or 0 when it could
    not be reached."""
    try:
        response = await http.post(
            device["endpoint"],
            content=encrypt(payload, p256dh=device["p256dh"], auth=device["auth"]),
            headers={
                "Authorization": vapid(device["endpoint"], private=private, subject=subject),
                "Content-Encoding": "aes128gcm",
                "Content-Type": "application/octet-stream",
                "TTL": str(TTL_SECONDS),
                "Urgency": "high",
            },
        )
    except httpx.HTTPError as exc:
        log.warning("push_unreachable", because=type(exc).__name__)
        return 0
    return response.status_code


async def deliver(
    devices: Sequence[Mapping[str, Any]], payload: bytes, *, private: str, subject: str
) -> dict[UUID, int]:
    """The payload to each device, and what each push service answered. No
    database connection is held while this waits on the network."""
    async with client() as http:
        return {
            device["id"]: await send(http, device, payload, private=private, subject=subject)
            for device in devices
        }


def delivered(status: int) -> bool:
    return 200 <= status < 300


async def record(conn: asyncpg.Connection, answers: Mapping[UUID, int]) -> None:
    """What an answer means for the device (docs/sales/02-data-model.md § 4):
    one that is gone is forgotten, one that was reached is remembered, and
    anything else is only counted — a push service has bad days too."""
    for device_id, status in answers.items():
        if status in (404, 410):
            await conn.execute("delete from push_subscriptions where id = $1", device_id)
        elif delivered(status):
            await conn.execute(
                """update push_subscriptions
                      set last_success_at = now(), failure_count = 0 where id = $1""",
                device_id,
            )
        else:
            await conn.execute(
                "update push_subscriptions set failure_count = failure_count + 1 where id = $1",
                device_id,
            )
```

- [ ] **Step 6: `notify()` asks for the push, and the handler sends it**

`events/handlers/notify.py` — its docstring's "from S7" becomes true. Imports gain `structlog`,
`get_settings`, `tenant_session`, `push`, and `Event, emit, handler` from `..bus`;
`log = structlog.get_logger()`.

```python
#: What reaches a phone (docs/sales/07-frontend.md § 8): somebody is waiting on
#: you, a task fell due, a lead turned hot. The rest stays in the bell — a
#: customer's every message, and whatever arrives in batches.
PUSHED = frozenset(
    {"assigned", "waiting_due_soon", "waiting_missed", "unassigned_waiting", "task_due", "lead_hot"}
)
```

`notify()` learns whether it wrote the row, and asks for the push in the same transaction:

```python
    """One row, once — and, for the kinds worth interrupting somebody for, one
    push. `dedupe_key` is what makes "once" true across retries: a row that was
    already there asks for nothing."""
    entity = entity or {}
    notification_id = await conn.fetchval(
        """insert into notifications (tenant_id, user_id, kind, title, body, href, entity,
                                      dedupe_key)
           values ($1, $2, $3, $4, $5, $6, $7, $8)
           on conflict do nothing
           returning id""",
        tenant_id,
        user_id,
        kind,
        title,
        body,
        href_for(entity),
        entity,
        dedupe_key,
    )
    if notification_id is not None and kind in PUSHED:
        await emit(
            conn,
            "notification.push_requested",
            {"notification_id": str(notification_id)},
            tenant_id=tenant_id,
            dedupe_key=f"push:{notification_id}",
            priority=8,
        )
```

The handler, in the same module:

```python
@handler("notification.push_requested")
async def on_push_requested(event: Event) -> None:
    """The notification, on every device its reader subscribed.

    Sent once: the push service does the retrying, for an hour (TTL), and a
    push later than that is worse than the bell it duplicates.
    """
    if event.tenant_id is None:
        raise ValueError("notification.push_requested requires a tenant")
    settings = get_settings()
    if not settings.vapid_private_key:
        log.info("push_skipped", because="VAPID_PRIVATE_KEY is not set")
        return
    notification_id = UUID(str(event.payload["notification_id"]))

    async with tenant_session(event.tenant_id) as conn:
        note = await conn.fetchrow(
            """select n.user_id, n.kind, n.title, n.body, n.href, t.slug
                 from notifications n join tenants t on t.id = n.tenant_id
                where n.id = $1""",
            notification_id,
        )
        if note is None:
            return
        devices = await conn.fetch(
            "select id, endpoint, p256dh, auth from push_subscriptions where user_id = $1",
            note["user_id"],
        )
    if not devices:
        return

    answers = await push.deliver(
        devices,
        push.message(
            note["title"],
            note["body"],
            href=f"/{note['slug']}{note['href'] or ''}",
            tag=note["kind"],
        ),
        private=settings.vapid_private_key,
        subject=settings.vapid_subject,
    )
    async with tenant_session(event.tenant_id) as conn:
        await push.record(conn, answers)
    log.info("pushed", kind=note["kind"], devices=len(devices))
```

`events/handlers/__init__.py` imports `notify` by name and lists it in `__all__` — its handler must
not depend on some other module happening to import it.

- [ ] **Step 7: Run them and see them pass**, then everything that notifies:

Run: `cd apps/api && uv run pytest tests/test_push_delivery.py tests/test_assignment.py tests/test_notifications.py tests/test_response_targets.py tests/test_task_due.py tests/test_crm_events.py tests/test_import_contracts.py -q`
Expected: PASS — `test_every_emitted_event_has_a_handler` now covers
`notification.push_requested`. A test that counted every event after a notification narrows to its
own type, as in B1.

- [ ] **Step 8: Commit**

```bash
git add apps/api/src/dealerai/config.py apps/api/src/dealerai/notifications/push.py apps/api/src/dealerai/events/handlers/notify.py apps/api/src/dealerai/events/handlers/__init__.py apps/api/tests/conftest.py apps/api/tests/test_push_delivery.py
git commit -m "feat(sales): the notification, on every device its reader subscribed"
```

---

## Task B5: A device subscribes, is listed, and can be tested — over HTTP

**Files:**
- Create: `apps/api/src/dealerai/routes/push.py`, `apps/api/src/dealerai/scripts/vapid.py`
- Modify: `apps/api/src/dealerai/main.py`, `.env.example`, `package.json`,
  `apps/web/lib/api/openapi.json`, `apps/web/lib/api/schema.ts` (generated)
- Test: `apps/api/tests/test_push_api.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_push_api.py` — `TestClient`, `reseed_with_people`, `_auth(user)` as in
`test_notifications.py`, and Task B4's `push_service` and `PHONE`. `SUBSCRIPTION` is `PHONE` plus
`"user_agent": "Mozilla/5.0 (Linux; Android 14) Chrome/130.0 Mobile"`.

- `test_the_key_a_browser_subscribes_with` — `GET /v1/push/key` is the public half of the configured
  key, 65 bytes; with no key configured, 503 `push-unavailable`.
- `test_a_device_subscribes_and_is_listed_to_its_owner_only` — `POST /v1/push-subscriptions` as
  SALES_1 → 201; `GET` lists it for SALES_1 with its `user_agent` — and no `endpoint`, `p256dh` or
  `auth` — and lists nothing for SALES_2.
- `test_subscribing_again_replaces_rather_than_adds` — the same body twice: one row.
- `test_keys_that_are_not_keys_are_refused` — a `p256dh` that is not a 65-byte uncompressed point,
  or an `auth` that is not 16 bytes: 400 naming the field.
- `test_an_address_that_is_no_push_service_is_refused` — `https://localhost:8000/v1/tenants`: 422,
  and no row.
- `test_removing_a_device` — `DELETE` → 204 and gone; somebody else's id → 404, still there.
- `test_a_test_push_goes_to_my_devices_now` — `POST /v1/push-subscriptions/test` → `{"sent": 1,
  "failed": 0}`; the request opens to a title of "DealerAI" and an `href` ending
  `/settings/notifications`; `last_success_at` is set.
- `test_a_test_push_forgets_a_device_that_is_gone` — the service answers 410: `{"sent": 0,
  "failed": 1}` and the list is empty.

- [ ] **Step 2: Run them and see them fail**

Run: `cd apps/api && uv run pytest tests/test_push_api.py -q`
Expected: FAIL — 404 on every route.

- [ ] **Step 3: The routes**

`routes/push.py`:

```python
"""A person's devices, for Web Push (docs/sales/06-api-contract.md § 8).

Everybody may subscribe their own device: there is no permission to hold,
because the rows are the caller's own (migration 0014) and a push carries only
what their bell already shows them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, status
from pydantic import BaseModel, Field, field_validator

from ..config import get_settings
from ..core.errors import AppError, NotFound, Unusable
from ..db.session import tenant_session
from ..deps import Ctx
from ..notifications import push

router = APIRouter(prefix="/v1", tags=["push"])


class PushUnavailable(AppError):
    status = 503
    slug = "push-unavailable"
    title = "Push is not configured"


class PushKey(BaseModel):
    public_key: str


def _decodes_to(value: str, length: int) -> bytes:
    try:
        raw = push.unb64(value)
    except ValueError as exc:
        raise ValueError("not base64url") from exc
    if len(raw) != length:
        raise ValueError(f"not {length} bytes")
    return raw


class PushSubscriptionIn(BaseModel):
    """What the browser's PushSubscription holds."""

    endpoint: str = Field(max_length=2048)
    p256dh: str = Field(max_length=200)
    auth: str = Field(max_length=64)
    user_agent: str | None = Field(default=None, max_length=512)

    @field_validator("p256dh")
    @classmethod
    def _a_p256_point(cls, value: str) -> str:
        if _decodes_to(value, 65)[0] != 4:
            raise ValueError("not an uncompressed point")
        return value

    @field_validator("auth")
    @classmethod
    def _a_secret(cls, value: str) -> str:
        _decodes_to(value, 16)
        return value


class PushDevice(BaseModel):
    """A device as its owner sees it — never the address or the keys."""

    id: UUID
    user_agent: str | None
    created_at: datetime
    last_success_at: datetime | None


class PushTest(BaseModel):
    sent: int
    failed: int


_DEVICE = "id, user_agent, created_at, last_success_at"


def _key() -> str:
    key = get_settings().vapid_private_key
    if not key:
        raise PushUnavailable("VAPID_PRIVATE_KEY is not set")
    return key


@router.get("/push/key", response_model=PushKey)
async def push_key(ctx: Ctx) -> PushKey:
    """The public half: what a browser subscribes with."""
    return PushKey(public_key=push.public_key(_key()))


@router.get("/push-subscriptions", response_model=list[PushDevice])
async def my_devices(ctx: Ctx) -> list[dict[str, Any]]:
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        rows = await conn.fetch(
            f"select {_DEVICE} from push_subscriptions order by created_at desc"  # noqa: S608
        )
    return [dict(row) for row in rows]


@router.post("/push-subscriptions", response_model=PushDevice, status_code=status.HTTP_201_CREATED)
async def subscribe(body: PushSubscriptionIn, ctx: Ctx) -> dict[str, Any]:
    """This device, for this person — whoever had it before (migration 0014)."""
    _key()
    if not push.is_push_service(body.endpoint):
        raise Unusable("that address is not a push service this server sends to")
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        device_id = await conn.fetchval(
            "select app.remember_push_subscription($1, $2, $3, $4, $5, $6)",
            ctx.tenant_id,
            ctx.user.id,
            body.endpoint,
            body.p256dh,
            body.auth,
            body.user_agent,
        )
        row = await conn.fetchrow(
            f"select {_DEVICE} from push_subscriptions where id = $1",  # noqa: S608
            device_id,
        )
    return dict(row)


@router.delete("/push-subscriptions/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unsubscribe(device_id: UUID, ctx: Ctx) -> None:
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        gone = await conn.fetchval(
            "delete from push_subscriptions where id = $1 returning id", device_id
        )
    if gone is None:
        raise NotFound("no such device")


@router.post("/push-subscriptions/test", response_model=PushTest)
async def test_push(ctx: Ctx) -> PushTest:
    """A push to the caller's own devices, now — how somebody finds out whether
    their phone will tell them, before a customer is what finds out."""
    settings = get_settings()
    key = _key()
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        devices = await conn.fetch("select id, endpoint, p256dh, auth from push_subscriptions")
        slug = await conn.fetchval("select slug from tenants where id = $1", ctx.tenant_id)
    answers = await push.deliver(
        devices,
        push.message(
            "DealerAI",
            "Notifications are on for this device.",
            href=f"/{slug}/settings/notifications",
            tag="test",
        ),
        private=key,
        subject=settings.vapid_subject,
    )
    async with tenant_session(ctx.tenant_id, user_id=ctx.user.id, scope=ctx.scope) as conn:
        await push.record(conn, answers)
    sent = sum(1 for answer in answers.values() if push.delivered(answer))
    return PushTest(sent=sent, failed=len(answers) - sent)
```

`main.py` imports `push` among the routes and includes `push.router` after `notifications.router`.

- [ ] **Step 4: A key for this machine, written and never printed**

`scripts/vapid.py`:

```python
"""A VAPID key for this machine's .env (`npm run vapid:keys`).

Written to the file, never to the terminal: a secret printed is a secret in a
scrollback, a log and a chat. The public half is not secret and is served at
GET /v1/push/key. Changing the key orphans every subscription made with the
old one, so a key that is already there is left alone.
"""

from __future__ import annotations

import re

from cryptography.hazmat.primitives.asymmetric import ec

from ..config import repo_root
from ..notifications.push import b64

LINE = re.compile(r"^VAPID_PRIVATE_KEY=.*$", re.M)


def main() -> int:
    path = repo_root() / ".env"
    text = path.read_text("utf-8") if path.exists() else ""
    existing = LINE.search(text)
    if existing and existing.group().partition("=")[2].strip():
        print("VAPID_PRIVATE_KEY is already set in .env; left alone.")
        return 0
    scalar = ec.generate_private_key(ec.SECP256R1()).private_numbers().private_value
    line = f"VAPID_PRIVATE_KEY={b64(scalar.to_bytes(32, 'big'))}"
    text = LINE.sub(line, text) if existing else f"{text.rstrip()}\n\n{line}\n"
    path.write_text(text, "utf-8")
    print("VAPID_PRIVATE_KEY written to .env. Restart the API and the worker.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

`package.json`: `"vapid:keys": "cd apps/api && uv run python -m dealerai.scripts.vapid"`.
`.env.example` gains, after the WhatsApp settings:

```
# Web Push (docs/sales/07-frontend.md § 8). `npm run vapid:keys` writes a private key
# here without printing it; without one nothing is pushed and the bell works as before.
# The subject is who a push service writes to about this sender: a real mailto: or
# https: address in production.
VAPID_PRIVATE_KEY=
VAPID_SUBJECT=mailto:push@dealerai.local
```

- [ ] **Step 5: Run them, then the contract**

Run: `cd apps/api && uv run pytest tests/test_push_api.py -q && uv run mypy src && uv run ruff check . && uv run ruff format --check .`, then `npm run api-types`.
Expected: PASS; `openapi.json` and `schema.ts` gain the five routes.

- [ ] **Step 6: Commit**

```bash
git add apps/api/src/dealerai/routes/push.py apps/api/src/dealerai/scripts/vapid.py apps/api/src/dealerai/main.py apps/api/tests/test_push_api.py .env.example package.json apps/web/lib/api/openapi.json apps/web/lib/api/schema.ts
git commit -m "feat(sales): a device subscribes, is listed, and can be tested"
```

---

## Task B6: Installable — the manifest, the icons, the worker, and a page for no network

**Files:**
- Create: `apps/web/app/manifest.ts`, `apps/web/app/icon.tsx`, `apps/web/app/apple-icon.tsx`,
  `apps/web/public/sw.js`, `apps/web/public/offline.html`, `apps/web/components/ServiceWorker.tsx`
- Modify: `apps/web/proxy.ts`, `apps/web/app/layout.tsx`, `apps/api/src/dealerai/routes/tenants.py`
- Test: `apps/web/app/manifest.test.ts`, `apps/web/lib/sw.test.ts`, `apps/web/proxy.test.ts`,
  `apps/api/tests/test_tenants.py`

- [ ] **Step 1: Write the failing tests**

`app/manifest.test.ts`:

- "is installable" — `manifest()` has a `name`, `start_url` `/`, `display` `standalone`, and PNG
  icons at 192 and 512, one of them `maskable`.

`lib/sw.test.ts` runs `public/sw.js` against a pretend worker scope — it is not a module, so the
test reads the file and hands it a `self` that collects its listeners, a `caches` and a `fetch`:

- "keeps the offline page and an icon, and nothing a customer said" — the install listener caches
  exactly `/offline.html` and `/icon/192`.
- "answers a page load with the offline page when there is no network" — a `navigate` request whose
  `fetch` rejects is answered with the cached page.
- "leaves everything else alone" — a request to `http://localhost:8000/v1/conversations` (mode
  `cors`) is not answered: `respondWith` is never called.
- "shows what was pushed" — a push whose `data.json()` is `{title, body, href, tag}` calls
  `showNotification(title, { body, tag, data: { href }, … })`.
- "opens what was tapped" — `notificationclick` closes the notification and focuses a window
  already on that address, or opens one.

`proxy.test.ts` — the matcher is a regular expression in a string; a too-greedy exclusion would
open pages, so it is pinned:

- "lets a browser fetch what makes the app installable" — `/manifest.webmanifest`, `/sw.js`,
  `/offline.html`, `/icon/192`, `/icon/512` and `/apple-icon` do not match.
- "still gates every page" — `/pollux-motors/inbox`, `/icon-motors/inbox`, `/icons`,
  `/apple-icon-cars/settings` and `/pollux-motors/settings/notifications` match.

`tests/test_tenants.py`:

- `test_a_workspace_cannot_take_an_address_the_app_answers_at` — `POST /v1/tenants` with slug
  `login`, `auth`, `icon`: 409, the same answer as a slug somebody has.

- [ ] **Step 2: Run them and see them fail**

Run: `npm run test --workspace web -- app/manifest.test.ts lib/sw.test.ts proxy.test.ts`, and
`cd apps/api && uv run pytest tests/test_tenants.py -q`
Expected: FAIL — no manifest, no worker, the matcher gates them all, and the slugs are accepted.

- [ ] **Step 3: The manifest and the icons**

`app/manifest.ts`:

```ts
import type { MetadataRoute } from "next";

/** What makes the app installable ([07] § 8). The icons are drawn in app/icon.tsx. */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "DealerAI",
    short_name: "DealerAI",
    description: "The dealership's customers, in one inbox.",
    start_url: "/",
    display: "standalone",
    background_color: "#0a2540",
    theme_color: "#0a2540",
    icons: [
      { src: "/icon/192", sizes: "192x192", type: "image/png" },
      { src: "/icon/512", sizes: "512x512", type: "image/png" },
      { src: "/icon/512", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
```

`app/icon.tsx` — a white **D** on the brand's navy, the letter inside the middle of the square so a
maskable crop keeps it:

```tsx
import { ImageResponse } from "next/og";

export function generateImageMetadata() {
  return [192, 512].map((size) => ({
    id: String(size),
    size: { width: size, height: size },
    contentType: "image/png",
  }));
}

/** The app's icon, as code: nothing binary to keep in step with the brand colour. */
export default async function Icon({ id }: { id: Promise<string> | string }) {
  const size = Number(await id);
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#0a2540",
          color: "white",
          fontSize: size * 0.5,
          fontWeight: 700,
        }}
      >
        D
      </div>
    ),
    { width: size, height: size },
  );
}
```

`app/apple-icon.tsx` is the same drawing at 180 × 180 (`export const size`, `contentType`).

- [ ] **Step 4: The service worker and its page**

`public/sw.js`:

```js
// The app's service worker (docs/sales/07-frontend.md § 8). It keeps one page —
// what to show with no network — and an icon; never an API response, and never
// anything a customer said. It shows what is pushed and opens what is tapped.
const CACHE = "dealerai-shell-v1";
const SHELL = ["/offline.html", "/icon/192"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) => cache.addAll(SHELL))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((names) => Promise.all(names.filter((n) => n !== CACHE).map((n) => caches.delete(n))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  // Only a page load that fails for want of a network gets the offline page.
  // Everything else — the API, the app's own files, images — is not ours to answer.
  if (event.request.mode !== "navigate") return;
  event.respondWith(fetch(event.request).catch(() => caches.match("/offline.html")));
});

self.addEventListener("push", (event) => {
  const said = event.data ? event.data.json() : {};
  event.waitUntil(
    self.registration.showNotification(said.title || "DealerAI", {
      body: said.body || undefined,
      tag: said.tag,
      data: { href: said.href || "/" },
      icon: "/icon/192",
      badge: "/icon/192",
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const href = new URL(event.notification.data?.href || "/", self.location.origin).href;
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((windows) => {
      const open = windows.find((w) => w.url === href);
      return open ? open.focus() : self.clients.openWindow(href);
    }),
  );
});
```

`public/offline.html` — one static page with no script and its own few lines of CSS, in both
languages: "You are offline. DealerAI needs a connection to show your customers." / "أنت غير متصل
بالإنترنت. يحتاج DealerAI إلى اتصال لعرض عملائك.", and a *Try again · حاول مرة أخرى* link to `/`.

- [ ] **Step 5: Through the gate, registered, and no workspace in the way**

`proxy.ts` — a signed-out browser can fetch what makes the app installable, and nothing else new:

```ts
export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|manifest.webmanifest$|sw.js$|offline.html$|icon/\\d+$|apple-icon$|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)",
  ],
};
```

`components/ServiceWorker.tsx`:

```tsx
"use client";

import { useEffect, useSyncExternalStore } from "react";

/** Chrome's offer to install. Not in lib.dom: only Chromium has it. */
type InstallOffer = Event & { prompt: () => Promise<unknown> };

let offer: InstallOffer | null = null;
const watchers = new Set<() => void>();

function keep(next: InstallOffer | null) {
  offer = next;
  watchers.forEach((watcher) => watcher());
}

/** The browser's offer to install the app, until it is taken — null on an
 *  iPhone, where installing is Share → Add to Home Screen, and once installed. */
export function useInstallOffer(): InstallOffer | null {
  return useSyncExternalStore(
    (watcher) => {
      watchers.add(watcher);
      return () => watchers.delete(watcher);
    },
    () => offer,
    () => null,
  );
}

/** Registers the service worker ([07] § 8) and keeps the offer to install. Renders nothing. */
export function ServiceWorker() {
  useEffect(() => {
    if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
    const offered = (event: Event) => {
      event.preventDefault(); // ours to show, in Settings → Notifications
      keep(event as InstallOffer);
    };
    const installed = () => keep(null);
    window.addEventListener("beforeinstallprompt", offered);
    window.addEventListener("appinstalled", installed);
    return () => {
      window.removeEventListener("beforeinstallprompt", offered);
      window.removeEventListener("appinstalled", installed);
    };
  }, []);
  return null;
}
```

`app/layout.tsx` renders `<ServiceWorker />` inside `<body>`, after `{children}`.

`routes/tenants.py` — beside `EMAIL`, and checked in `create_tenant` before the insert, with the
sentence a taken slug already gets:

```python
#: Addresses the web app itself answers at its root (apps/web/app). A workspace
#: with one of these as its slug could never be opened: the app's own page
#: would answer instead.
RESERVED_SLUGS = frozenset(
    {"login", "signup", "auth", "onboarding", "accept-invite", "dev-login", "icon", "apple-icon"}
)
```

```python
    if body.slug in RESERVED_SLUGS:
        raise Conflict(f"the slug {body.slug!r} is taken")
```

- [ ] **Step 6: Run the checks**

Run: `npm run check --workspace web`, and `cd apps/api && uv run pytest tests/test_tenants.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/web/app/manifest.ts apps/web/app/manifest.test.ts apps/web/app/icon.tsx apps/web/app/apple-icon.tsx apps/web/public/sw.js apps/web/public/offline.html apps/web/lib/sw.test.ts apps/web/components/ServiceWorker.tsx apps/web/proxy.ts apps/web/proxy.test.ts apps/web/app/layout.tsx apps/api/src/dealerai/routes/tenants.py apps/api/tests/test_tenants.py
git commit -m "feat(web): installable, with a service worker that keeps nothing a customer said"
```

---

## Task B7: Settings → Notifications

**Files:**
- Create: `apps/web/lib/push.ts`, `apps/web/components/settings/NotificationSettings.tsx`,
  `apps/web/app/[tenant]/settings/notifications/page.tsx`
- Modify: `apps/web/components/settings/sections.ts`, `apps/web/lib/api/hooks.ts`,
  `apps/web/lib/api/keys.ts`, `apps/web/messages/{en,ar}.ts`
- Test: `apps/web/lib/push.test.ts`, `apps/web/components/settings/NotificationSettings.test.tsx`,
  `apps/web/components/settings/sections.test.ts`

- [ ] **Step 1: Write the failing tests**

`lib/push.test.ts`:

- "turns the server's key into what subscribe() takes" — `keyBytes` of the RFC's public key is 65
  bytes starting with 4.
- "knows an iPhone that has not been added to the Home Screen" — `needsHomeScreen(userAgent,
  standalone)` is true for an iPhone Safari user agent in a tab, false once standalone, false for
  Android Chrome.
- "names a device by its browser and system" — "Chrome · Android", "Safari · iPhone", "Chrome ·
  iPhone" (CriOS), "Edge · Windows", "Firefox · Linux", and an empty name for nothing at all.

`components/settings/sections.test.ts`:

- "lets anyone open their notifications" — `mayOpen("/pollux-motors/settings/notifications", [])`.
- "still starts a salesperson on the quick replies" — `firstSection([])` is Quick replies.

`components/settings/NotificationSettings.test.tsx` (`@/lib/api/hooks`, `@/lib/push` and
`@/components/ServiceWorker` mocked):

- "says so when this browser cannot push" — `supportsPush()` false: `notifications.unsupported`,
  and no button to turn anything on.
- "explains the Home Screen first on an iPhone" — `needsHomeScreen` true: the iOS note, no button.
- "says when the server has no key" — the key query failed: `notifications.unconfigured`.
- "turns notifications on for this device" — the button calls `subscribeThisDevice(key)`, then
  `useSubscribeDevice().mutate` with what it returned, and remembers the id the API answered with.
- "says when the browser has been told no" — `subscribeThisDevice` rejects with "denied":
  `notifications.blocked`.
- "lists my devices, marks this one, and removes one" — two devices; the remembered id is marked
  *This device*; Remove calls `useRemoveDevice().mutate(id)`, and removing this one also silences
  the browser.
- "sends a test and says how it went" — `{sent: 2, failed: 0}` reads "Sent to 2 devices".
- "offers to install when the browser does" — an install offer: the button calls its `prompt()`.

- [ ] **Step 2: Run them and see them fail**

Run: `npm run test --workspace web -- lib/push.test.ts components/settings`
Expected: FAIL.

- [ ] **Step 3: `lib/push.ts`**

```ts
/** What the browser side of Web Push needs ([07] § 8). */

export function supportsPush(): boolean {
  return "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
}

/** The server's base64url key as the bytes subscribe() takes. */
export function keyBytes(base64url: string) {
  const base64 = base64url.replace(/-/g, "+").replace(/_/g, "/");
  return Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
}

/** On an iPhone, notifications only work once the app is on the Home Screen (iOS 16.4+). */
export function needsHomeScreen(userAgent: string, standalone: boolean): boolean {
  return /iPhone|iPad|iPod/.test(userAgent) && !standalone;
}

export function isStandalone(): boolean {
  return (
    window.matchMedia("(display-mode: standalone)").matches ||
    (navigator as { standalone?: boolean }).standalone === true
  );
}

// Order matters: Edge and Chrome both say Safari, an iPhone says Mac, Android says Linux.
const BROWSERS = [
  ["Edg/", "Edge"],
  ["Firefox/", "Firefox"],
  ["CriOS/", "Chrome"],
  ["Chrome/", "Chrome"],
  ["Safari/", "Safari"],
];
const SYSTEMS = [
  ["iPhone", "iPhone"],
  ["iPad", "iPad"],
  ["Android", "Android"],
  ["Windows", "Windows"],
  ["Mac OS X", "Mac"],
  ["Linux", "Linux"],
];

/** "Chrome · Android" — enough to tell two of your own devices apart, with no
 *  word to translate. Empty when the browser said nothing we recognise. */
export function deviceName(userAgent: string | null | undefined): string {
  const named = (table: string[][]) => table.find(([mark]) => (userAgent ?? "").includes(mark))?.[1];
  return [named(BROWSERS), named(SYSTEMS)].filter(Boolean).join(" · ");
}

/** Ask, subscribe, and hand back what the API stores. Throws "denied" when the
 *  person — or their browser's settings — said no. */
export async function subscribeThisDevice(publicKey: string) {
  if ((await Notification.requestPermission()) !== "granted") throw new Error("denied");
  const registration = await navigator.serviceWorker.ready;
  const options = { userVisibleOnly: true, applicationServerKey: keyBytes(publicKey) };
  const subscription = await registration.pushManager.subscribe(options).catch(async () => {
    // Subscribed once with another server's key: drop that and ask again.
    await (await registration.pushManager.getSubscription())?.unsubscribe();
    return registration.pushManager.subscribe(options);
  });
  const { endpoint, keys } = subscription.toJSON();
  if (!endpoint || !keys?.p256dh || !keys.auth) throw new Error("incomplete");
  return { endpoint, p256dh: keys.p256dh, auth: keys.auth, user_agent: navigator.userAgent };
}

/** Stop this browser receiving pushes. The push service then answers "gone"
 *  for it, and the server forgets the device. Never throws: nothing that
 *  calls this should fail over a notification. */
export async function silenceThisDevice(): Promise<void> {
  try {
    rememberDevice(null);
    if (!("serviceWorker" in navigator)) return;
    const registration = await navigator.serviceWorker.getRegistration();
    await (await registration?.pushManager?.getSubscription())?.unsubscribe();
  } catch {
    // An unsupported or half-supported browser has nothing to silence.
  }
}

const DEVICE = "push-device";

/** Which listed device is this browser: the id the API gave it, kept here.
 *  Storage can be refused (a private window); then no device is marked. */
export function rememberedDevice(): string | null {
  try {
    return localStorage.getItem(DEVICE);
  } catch {
    return null;
  }
}

export function rememberDevice(id: string | null): void {
  try {
    if (id) localStorage.setItem(DEVICE, id);
    else localStorage.removeItem(DEVICE);
  } catch {
    // See rememberedDevice.
  }
}
```

- [ ] **Step 4: The hooks, the section, the screen**

`keys.ts`: `pushKey`, `pushDevices`. `hooks.ts`: `usePushKey()` (`GET /v1/push/key`, `retry: false`
— a 503 is an answer), `usePushDevices()`, `useSubscribeDevice()` (`POST`, invalidates the devices),
`useRemoveDevice()` (`DELETE`), `useTestPush()` (`POST …/test`, invalidates the devices: a test can
forget one).

`sections.ts` appends `{ href: "/settings/notifications", key: "settings.notifications" }` — last,
with no permission: everybody has a phone, and `firstSection`'s fallback stays Quick replies.

`NotificationSettings.tsx`, in order: what you will be told; this device; installing; my devices; a
test. The decision-carrying parts:

```tsx
  // undefined until the browser has been asked: none of this exists on the server.
  const [device, setDevice] = useState<
    { can: boolean; homeScreen: boolean; mine: string | null } | undefined
  >(undefined);
  useEffect(() => {
    setDevice({
      can: supportsPush(),
      homeScreen: needsHomeScreen(navigator.userAgent, isStandalone()),
      mine: rememberedDevice(),
    });
  }, []);

  const on = Boolean(device?.mine && (devices.data ?? []).some((d) => d.id === device.mine));

  async function turnOn() {
    setProblem(null);
    try {
      const subscription = await subscribeThisDevice(key.data!.public_key);
      subscribe.mutate(subscription, {
        onSuccess: (saved) => {
          rememberDevice(saved.id);
          setDevice((current) => current && { ...current, mine: saved.id });
        },
        onError: () => setProblem(t("notifications.failed")),
      });
    } catch (error) {
      setProblem(
        (error as Error).message === "denied" ? t("notifications.blocked") : t("notifications.failed"),
      );
    }
  }

  function forget(id: string) {
    remove.mutate(id);
    if (id === device?.mine) {
      // This browser: stop it at the source too, or it would say "on" and hear nothing.
      void silenceThisDevice();
      setDevice((current) => current && { ...current, mine: null });
    }
  }
```

This device says, first match wins: the Home Screen note (`homeScreen`) · unsupported (`!can`) ·
unconfigured (the key query failed) · *on* · the button. A device removed elsewhere is no longer in
the list, so this browser reads *off* and offers the button again — it never claims a push it would
not get.

Strings, both languages:

| Key | English | Arabic |
|---|---|---|
| `settings.notifications` | Notifications | الإشعارات |
| `notifications.what` | Your phone tells you when a customer is assigned to you, when one has waited too long, when a task falls due and when a lead turns hot — even with the app closed. | يخبرك هاتفك عند إسناد عميل إليك، وعند تأخر الرد عليه، وعند حلول موعد مهمة، وعندما تصبح فرصة ساخنة — حتى والتطبيق مغلق. |
| `notifications.thisDevice` | This device | هذا الجهاز |
| `notifications.turnOn` | Turn on notifications on this device | فعّل الإشعارات على هذا الجهاز |
| `notifications.on` | Notifications are on for this device. | الإشعارات مفعّلة على هذا الجهاز. |
| `notifications.unsupported` | This browser cannot receive notifications. | هذا المتصفح لا يستقبل الإشعارات. |
| `notifications.unconfigured` | Notifications are not set up on this server yet. | الإشعارات غير مهيأة على هذا الخادم بعد. |
| `notifications.blocked` | Notifications are blocked for this site. Allow them in your browser's settings, then try again. | الإشعارات محظورة لهذا الموقع. اسمح بها من إعدادات المتصفح ثم حاول مرة أخرى. |
| `notifications.failed` | That did not work. Try again. | لم ينجح ذلك. حاول مرة أخرى. |
| `notifications.ios` | On an iPhone: tap Share, then Add to Home Screen, and open DealerAI from there to turn notifications on. | على الآيفون: اضغط «مشاركة» ثم «إضافة إلى الشاشة الرئيسية»، وافتح DealerAI من هناك لتفعيل الإشعارات. |
| `notifications.install` | Install the app | ثبّت التطبيق |
| `notifications.devices` | My devices | أجهزتي |
| `notifications.noDevices` | No device is subscribed yet. | لا يوجد جهاز مشترك بعد. |
| `notifications.someDevice` | A device | جهاز |
| `notifications.lastReached` | last reached | آخر وصول |
| `notifications.neverReached` | not reached yet | لم يصله إشعار بعد |
| `notifications.remove` | Remove | إزالة |
| `notifications.test` | Send a test notification | أرسل إشعارًا تجريبيًا |
| `notifications.testSent` | Sent to this many devices: | أُرسل إلى هذا العدد من الأجهزة: |
| `notifications.testFailed` | Could not reach this many: | تعذّر الوصول إلى هذا العدد: |

- [ ] **Step 5: Run the checks**

Run: `npm run check --workspace web`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/web/lib/push.ts apps/web/lib/push.test.ts apps/web/components/settings/NotificationSettings.tsx apps/web/components/settings/NotificationSettings.test.tsx "apps/web/app/[tenant]/settings/notifications/page.tsx" apps/web/components/settings/sections.ts apps/web/components/settings/sections.test.ts apps/web/lib/api/hooks.ts apps/web/lib/api/keys.ts apps/web/messages/en.ts apps/web/messages/ar.ts
git commit -m "feat(web): Settings → Notifications: this device, my devices, a test"
```

---

## Task B8: Signing out, which silences the device first

**Files:**
- Create: `apps/web/lib/auth/sign-out.ts`, `apps/web/components/SignOutButton.tsx`
- Modify: `apps/web/app/[tenant]/settings/layout.tsx`, `apps/web/components/auth/JoinInvitation.tsx`,
  `apps/web/messages/{en,ar}.ts`
- Test: `apps/web/components/SignOutButton.test.tsx`

- [ ] **Step 1: Write the failing tests**

`components/SignOutButton.test.tsx` (`@/lib/push`, `@/lib/supabase/client` and `@/lib/dev-auth`
mocked):

- "silences this device before the session ends" — the order of calls is `silenceThisDevice`, then
  `auth.signOut`.
- "then leaves for the front door" — `window.location.assign("/")`, where the gate sends a
  signed-out visitor to sign-in.
- "clears the local session in dev mode" — with `DEV_AUTH`, the `dev_token` cookie is gone and
  Supabase is not called.

- [ ] **Step 2: Run them and see them fail**

Run: `npm run test --workspace web -- components/SignOutButton.test.tsx`
Expected: FAIL — the component does not exist.

- [ ] **Step 3: One way out**

`lib/auth/sign-out.ts`:

```ts
import { DEV_AUTH } from "@/lib/dev-auth";
import { silenceThisDevice } from "@/lib/push";
import { createClient } from "@/lib/supabase/client";

/** Signing out, wherever the session lives — after silencing this device: a
 *  phone that changes hands must not keep showing the last person's customers
 *  on its lock screen. */
export async function signOut(): Promise<void> {
  await silenceThisDevice();
  if (DEV_AUTH) document.cookie = "dev_token=; path=/; max-age=0; samesite=lax";
  else await createClient().auth.signOut();
}
```

`components/SignOutButton.tsx` — a client button, `t("auth.signOut")`, that awaits `signOut()` and
then `window.location.assign("/")`. `app/[tenant]/settings/layout.tsx` renders it after the
sections, inside the same `<nav>`: one place that is on screen on a phone and on a desk.
`JoinInvitation.tsx` drops its own copy for `signOut().then(() => window.location.reload())`.

Strings: `auth.signOut` — Sign out / تسجيل الخروج.

- [ ] **Step 4: Run the checks**

Run: `npm run check --workspace web`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/web/lib/auth/sign-out.ts apps/web/components/SignOutButton.tsx apps/web/components/SignOutButton.test.tsx "apps/web/app/[tenant]/settings/layout.tsx" apps/web/components/auth/JoinInvitation.tsx apps/web/messages/en.ts apps/web/messages/ar.ts
git commit -m "feat(web): signing out, which silences the device first"
```

---

## Task B9: The whole check, then a push in a browser

**Files:**
- Modify: `docs/sales/plans/s7-pilot-readiness.md` (a Part B review), `docs/sales/README.md`

- [ ] **Step 1: The whole check**

Stop the worker. Run: `npm run check && npm run check:openapi`
Expected: every suite green, the guards at 100%, no drift.

- [ ] **Step 2: The path, locally, in a browser**

`npm run vapid:keys`, `npm run db:seed`, the API, the worker and the web app. Write down what
actually happens:

1. Signed out, the browser is served `/manifest.webmanifest` (it parses, and its icons are PNGs of
   the size they claim), `/sw.js` and `/offline.html`; every page is still gated.
2. The worker registers; its cache holds exactly the offline page and one icon.
3. With the network cut, a page load shows the offline page in both languages; back online, the app.
4. **Ahmed** opens Settings → Notifications — it is there for a salesperson — and turns
   notifications on: one `push_subscriptions` row, listed and marked as this device.
5. *Send a test notification*: the count comes back, and the notification arrives.
6. A simulated customer is assigned to Ahmed: his device is pushed "A customer is waiting for you";
   tapping it opens the conversation.
7. A task of his created to fall due in a minute: `task_due` in the bell, and pushed.
8. A device the push service calls gone disappears from his list.
9. Signing out silences the device: the browser's subscription is gone.
10. Arabic at 375 px: the Notifications screen reads right to left with no sideways scroll, and the
    iOS note shows for an iPhone that has not added the app.

Where this machine's browser has no push service to subscribe with, steps 4–8 are recorded as
verified against the automated push service of Tasks B4 and B5 — which opens what was sent with the
device's own key — and a real phone is Part D's.

- [ ] **Step 3: The review, and commit**

Append `## Part B review — <date>` to this plan, in the shape of Part A's, and update the Code row
in `docs/sales/README.md`.

```bash
git add docs/sales/plans/s7-pilot-readiness.md docs/sales/README.md
git commit -m "docs(sales): S7 Part B, installable app and push, with the run recorded"
```

---

## Spec coverage (Part B)

| Requirement | Task |
|---|---|
| [07](../07-frontend.md) §8 — `app/manifest.ts`; a service worker caching only the shell and static assets, never API responses or customer data; an offline page | B6 |
| §8 — install prompts: `beforeinstallprompt`, and the explanation on iOS Safari | B6 (kept), B7 (shown) |
| §8 — Web Push with VAPID; subscribe in Settings → Notifications; `POST /v1/push-subscriptions`; the worker sends | B3, B4, B5, B7 |
| §8 — Phase 1 sends assignment, waiting-too-long, task-due and hot-lead | B4 (`PUSHED`); B1–B2 (task-due did not exist) |
| [06](../06-api-contract.md) §7 — `POST` and `DELETE /v1/push-subscriptions` | B5, with the list, the key and the test the screen needs |
| [02](../02-data-model.md) §4 — `push_subscriptions`, a row deleted on 404 or 410; own rows | B1, B4 |
| [05](../05-workflows.md) §1 — `notification.push_requested`, priority 8 | B4 |
| [08](../08-screens.md) §13 — Notifications (everyone): enable push, per-device list, a test notification, the iOS note | B7 |

## Execution (Part B)

Inline in this session with `superpowers:executing-plans`, as Part A was — no subagents unless
asked. Checkpoints after Task B5 (the backend), Task B8 (the app), and Task B9.

---

## Part B review — 2026-10-02

Nine tasks, then the path in a browser against a freshly seeded workspace with the API, the worker
and the web app running. The findings the plan fixed are in its table above; these are what
building it and running it found besides.

| Found | Why it mattered | Fixed in |
|---|---|---|
| The RFC's example in this plan had gained a character on the way here | The code matched the RFC the first time and failed the test. The test now holds the RFC's raw text, and the whole message of its Section 5 as well | `7c0867f` |
| A `p256dh` of the right length that is no point on the curve was accepted | The worker would have raised on every push to it, for ever. It is refused when it is offered | `9344863` |
| A browser with no push service behind it never answers `subscribe()` | Playwright's Chromium grants the permission and then says nothing: the button stayed disabled for good. It gives up after twenty seconds and says so | `f668919` |
| httpx writes every request's whole URL into the log | The worker's log held each device's push endpoint — the address of somebody's phone. HTTP clients log warnings only; our own events already say what was sent | `4decf23` |
| A date formatted for Arabic was wrapped in `dir="ltr"` | "Last reached" came out with its day behind the time — and so did the invitation's "valid until" from Part A. Only a screenshot showed it: the text was right. Dates flow with their sentence now | `1637d73` |
| Every setting must be in `.env.example`, and a test says so | The VAPID settings moved from B5 into B4, with the setting | `4ff5692` |

Different from the plan, on purpose: the screen's strings are `push.*`, because the bell already
owns `notifications.*`, and the section reuses the bell's title; what the browser can do is read
with `useSyncExternalStore` rather than set from an effect, so the first paint matches the server's;
and `is_push_service` also refuses a string that is no URL at all.

Sound as built, and left alone: the trigger — the seed's three overdue tasks announced themselves
the moment a worker started, with no code in the seed; one notification, one push, however often
the queue retried; a device removed elsewhere reading *off* here rather than claiming a push it
would not get; and the gate, which opened for six addresses and nothing that merely starts like one.

Known and deliberately not changed in Part B:

- **No browser on this machine could subscribe.** The Browser pane refuses notifications and
  Playwright's Chromium has no push service. Steps 4–8 below therefore ran against a stand-in on
  `127.0.0.1` that plays the push service and the phone — it checks the VAPID signature against the
  server's published key and opens the body with a device key of its own — with the device rows put
  in by hand. A subscription made by a real browser, a push accepted by Google's, Apple's or
  Mozilla's service, and a notification on a lock screen are Part D's, on staging, with real phones.
  `VAPID_SUBJECT` must be a real address there.
- Notification titles are English whatever the reader's language (Part C).
- An iPad calls itself a Mac, so in a tab it reads "cannot receive notifications" rather than the
  Home Screen note.
- In a private window the browser cannot remember which listed device it is; everything else works.
- A new customer went to the manager: routing takes the team member with the fewest open chats, and
  a manager in the team is one while her switch is on. Not Part B's to change.
- The suite deletes every tenant in the database the app is using. During this run it took the
  workspace from under somebody who was looking at the app, so the final check ran against a second
  database on the same server. Making that the default is a small change worth its own task.

**Checks, final:** `npm run check` — 1,527 backend tests, the guards at 100% branch coverage, 235
web tests, types, lint and logical CSS; `npm run check:openapi` — no drift.

**Verified end to end on 2026-10-02:**

1. Signed out, the browser was served `/manifest.webmanifest`, `/icon/192` and `/icon/512` (PNGs of
   the size they claim), `/apple-icon`, `/sw.js` and `/offline.html`; `/pollux-motors/inbox` and
   `/icon-motors/inbox` were still sent to sign-in. Chromium, asked through its DevTools protocol,
   parsed the manifest with no errors and gave one reason not to install: the test window was
   incognito.
2. The service worker registered, took the page, and its cache held exactly `/offline.html` and
   `/icon/192`.
3. With the web server stopped, loading `/pollux-motors/inbox` showed the offline page — both
   languages, no script, the address unchanged; with it back, the app.
4. **Ahmed**, a salesperson, saw three things under Settings: Quick replies, Notifications, Sign
   out. Turning notifications on in the pane said "Notifications are blocked for this site", which
   is true of the pane. With his device in place the screen read "Notifications are on for this
   device" and listed "Chrome · Android · This device" — his, and nobody else's of the four.
5. *Send a test notification*: "Sent to this many devices: 1". The stand-in verified the signature
   (ES256, for its own origin, twelve hours), saw `aes128gcm`, `TTL: 3600` and `Urgency: high`, and
   opened 237 bytes into "DealerAI — Notifications are on for this device." and the address of this
   screen. The row then read "last reached 2 Oct 2026, 10:44".
6. With the worker started: the three overdue tasks went to Salem's and Mohamed's devices at
   once; "Mona Fathy is waiting" to Ahmed and to Sara; "James Whitfield is waiting", unassigned,
   to Sara. A new customer through `npm run wa:simulate` was assigned to Sara, whose device got "A
   customer is waiting for you" six seconds later, with the conversation's address. The morning
   brief and the customer's own message were written to the bell and pushed to nobody. Opened as
   Ahmed, the address pushed to him showed Mona's conversation.
7. A task added on the Tasks screen for 10:50, a minute ahead, reached Ahmed's device at 10:50:06:
   "Due now: Send Mona the Land Cruiser price".
8. With the stand-in answering 410, the test read "Sent to this many devices: 0 · Could not reach
   this many: 1", the device left the list, and *This device* offered the button again.
9. *Sign out* forgot the device, left no subscription and no session, and the gate sent the browser
   to sign-in.
10. Arabic at 375 px, as an iPhone and as an Android phone: right to left, no sideways scroll. The
    iPhone got the Home Screen note in place of the button; the Android read "الإشعارات مفعّلة على
    هذا الجهاز". The first screenshot is what showed the scrambled date.

---

# Part C — Arabic and accessibility pass

**Goal:** a salesperson who reads Arabic works a whole day in the app on a phone without meeting a
scrambled number, a sentence in English that the app itself wrote, or a control they cannot reach:
times, phone numbers and prices read the right way round; what a customer wrote keeps its own
direction; the app's own words — refusals, notifications, statuses — are in the reader's language;
and every dialog, menu and page can be used with a keyboard and makes sense to a screen reader.

**How this part was planned.** By looking first. Every Sales screen was opened in Arabic at 375 px
as a salesperson, a manager and the owner — 40 states in all, counting the panels, drawers, menus
and dialogs a page load does not show — each with a screenshot, a sideways-overflow measurement and
`axe-core`'s verdict (it is already installed, under the lint config), and a screenshot of every
kind of screen was read. The table below is what that found. The layout held everywhere: no screen
scrolled sideways, and no catalogue string was missing. What was wrong was inside the lines.

**Architecture:** four ideas, each applied everywhere it is needed rather than screen by screen.
(1) *Formatters take the reader's language* — a duration or an age is a phrase, and `lib/format.ts`
says it in Arabic units when asked, so no caller composes one. (2) *Text keeps its own direction* —
what a person wrote is `dir="auto"`, and what is a number is `dir="ltr"`, through two tiny
components so the rule has one home. (3) *The server learns the reader's language twice*: per
request, from `Accept-Language`, for what it refuses; and per person, in `profiles.locale`, for what
it tells them later — a notification is written when its reader is not there to ask. (4) *A dialog is
a `<dialog>`* — the platform's own modal traps focus, closes on Escape and gives focus back, so one
small wrapper replaces four hand-made overlays and two sheets.

**Tech stack:** Next.js 16 · Tailwind 4 · `Intl` · the HTML `<dialog>` element · FastAPI ·
Postgres 17 · Vitest · pytest · `axe-core` (already present, for the audit only).

**Before you start:**

- Docker Desktop running; the API and the web app up; `npm run db:seed`.
- **Run the suite against the scratch database** (`dealerai_test`, with `DATABASE_URL` and
  `MIGRATION_DATABASE_URL` overridden), so a run does not empty the workspace somebody is looking
  at.
- Read [07](../07-frontend.md) §6 and §10, and [08](../08-screens.md) §15.
- Never run `prettier` over the message catalogues: it re-wraps lines nobody touched.

**Found by the audit** — fixed in the tasks named:

| Found | Why it matters | Task |
|---|---|---|
| Durations and ages are English in Arabic: "تأخر الرد 38m 51s", "23h", "4m" | The number a salesperson watches all day is the one thing left untranslated | C1 |
| "<1m" comes out as "1m>" | The sign is mirrored; it reads as *more* than a minute | C1 |
| The lead drawer's date is formatted in English, for Dubai, whatever the workspace: "Sept 2026, 11:25 30" | The day has slid behind the time, as in Part B | C1 |
| Phone numbers read "971500000104+" | A number copied from the screen is wrong | C2 |
| A French or English message in the Arabic thread has its full stop or question mark at the front; the customer timeline too | [07](../07-frontend.md) §6 says customer text is `dir="auto"`. The inbox and CRM screens (S2, S3) were built before that was applied | C2 |
| A Latin name or task title is cut from its start: "… Al Mazrouei", "…bout the passport copy" | In a right-to-left line the overflow leaves by the left, which is where a Latin run begins | C2 |
| "Export documents/documents", "2024Negotiation", "ARأهلاً" — two things with no space between them | `ms-2` on an element with its own direction puts the margin on the far side | C2 |
| The thread's back arrow points away from where it goes | "←" is a character; it does not mirror | C2 |
| "+10" beside a score reason reads "10+" | Same cause as the phone numbers | C2 |
| `connected`, `utility`, `approved`, `whatsapp`, `local` shown as they are stored | The S6 review's "raw English words" | C3 |
| Score reasons ("Asked whether it is available") and a blocked draft's reason are English sentences the API composed | They are chosen from a short list, so they can be said in the reader's language | C3 |
| "2 أشخاص", "0 يوم هنا", "1 مقاطع" | Arabic counts are six forms, not two. The S6 review's item | C3 |
| "صباح الخير, Ahmed" — a Latin comma | Small, and on the first screen of the day | C3 |
| A refusal is an English sentence in the Arabic UI: "Qualified still holds 1 lead. Move them first." | The S6 review's item. About 35 of the API's refusals can be caused from a screen | C5 |
| A sign-in failure shows Supabase's own English sentence | The one message on the first screen | C5 |
| Notification titles are English whatever the reader reads — in the bell, and now on a lock screen | The S2 review's item, and Part B's | C4, C6 |
| The brief's notification carries the English headline though an Arabic one is written beside it | It was always there to use | C6 |
| Erase, Merge, Hand over and Lost-reason are `div`s with `role="dialog"`: focus stays behind them, Tab walks the page underneath, Escape does nothing | [07](../07-frontend.md) §10: focus trapped and restored in dialogs | C7 |
| The customer panel and the lead drawer cover the phone's whole screen and are not dialogs at all | A screen reader is never told the page changed | C7 |
| The inbox, an unavailable settings section and a bad invitation have no `h1`; Channels goes from `h1` to `h3`; two navigation landmarks share one name; the offline page has no `main` | `axe`: page-has-heading-one, heading-order, landmark-unique, region | C8 |
| The thread is not a `log`, so a new message is silent to a screen reader | [07](../07-frontend.md) §10 | C8 |
| The quick-reply menu's options hold a button each | `axe`: nested-interactive, serious | C8 |
| The time and the ticks on a sent message fail contrast on the gold bubble | `axe`: color-contrast, serious | C9 |
| The thread's back link is 12 × 20 px; a source chip is 26 px high | Under a thumb, on the screen used most | C9 |
| Arabic headings are letter-spaced (`tracking-wide`) | It pulls joined letters apart; [07](../07-frontend.md) §6 forbids it | C9 |
| Nothing honours `prefers-reduced-motion`, and focus is whatever the browser draws | [07](../07-frontend.md) §10 | C9 |
| On a phone the owner's nine settings sections are one scrolling row of three-line labels, with Sign out at the far end | Part A noted it at seven | C9 |
| On the dashboard at 375 px a waiting customer's name is squeezed to nothing beside the hand-over menu | The row says who is waiting for everyone but the one it cannot fit | C9 |
| Knowledge's file chooser reads "No file chosen · Choose File" | Those are the browser's words, in the browser's language, not the app's | C9 |
| With the 24-hour window closed the composer says "send a template" and offers no way to | S2's plan had a template picker; it was never built. A customer who wrote yesterday can only be answered from the phone | C10 |

## What Part C does not build

| Item | Why, and when |
|---|---|
| What the model writes for the team — a draft's "needs a person" sentence, action chips, the summary and next step, a follow-up's reason — in Arabic | S4 made these English on purpose: read by the team, not the customer. Changing it is a setting ("the team's language") and three prompts, with the copilot's evals re-run. A decision for the dealership, not a pass; asked of the owner in this part's report |
| Per-vehicle Arabic names for the inventory guard | S4 → S6 → here, and it is not a matter of language in the UI: it is the copilot's guard, with its own evals. The reserved-car check already covers the car that was asked about. With the copilot's next slice |
| The keyboard map ([07](../07-frontend.md) §10: J/K, R, N, G then I…) | Shortcuts for a desk; the pilot's salespeople are on phones. Everything is reachable with Tab, Enter and Escape, which is what this part checks. When somebody works the inbox from a desk all day |
| Web fonts (Geist, IBM Plex Sans Arabic) | The system's own Arabic face is on every phone and costs nothing to load. If Pollux wants one look everywhere |
| Stage and team names in two languages | They are the dealership's own words (S3). A new workspace's default stages are English; a manager renames them in Settings → Pipelines |
| The Marketing screens (Command Center, Content, Approvals, Inventory) | DealerAI OS's, not the Sales module's. Command Center has four English labels |

## File structure

| File | Responsibility |
|---|---|
| `apps/web/lib/format.ts` | **Modify.** Durations, ages and dates in the reader's language |
| `apps/web/components/Bidi.tsx` | **Create.** `<Ltr>` for what is a number, `<Auto>` for what a person wrote |
| `apps/web/components/inbox/*`, `components/crm/*`, `components/manager/WaitingList.tsx`, `app/[tenant]/{today,customers,dashboard}/…` | **Modify.** Direction, spacing and arrows; the formatters' new argument |
| `apps/web/lib/words.ts` | **Create.** A stored code as a word: `word(t, "channel.status", value)`; `counted()` |
| `apps/web/messages/{en,ar}.ts` | **Modify.** The words for codes, the count phrases, the new strings |
| `supabase/migrations/0015_sales_reader_language.sql` | **Create.** `profiles.locale`, `app.set_locale()` |
| `apps/api/src/dealerai/routes/me.py` | **Modify.** `locale` on `/v1/me`; `PUT /v1/me/locale` |
| `apps/web/app/[tenant]/providers.tsx`, `lib/api/{client,hooks}.ts`, `lib/api.ts` | **Modify.** Telling the server the reader's language, per request and once per change |
| `apps/api/src/dealerai/core/errors.py`, `routes/*.py` | **Modify.** `ar=` on a refusal; the handler chooses by `Accept-Language` |
| `apps/api/src/dealerai/events/handlers/{notify,inbox,crm,copilot,manager}.py` | **Modify.** A notification's words in both languages; the reader's chosen on insert |
| `apps/web/components/Modal.tsx` | **Create.** One modal on `<dialog>` |
| `apps/web/components/crm/{Erase,Merge,Reassign,LostReason}Dialog.tsx`, `CustomerPanel.tsx`, `LeadDrawer.tsx`, `components/NotificationsBell.tsx` | **Modify.** Onto `Modal`; the bell closes on Escape |
| `apps/web/components/inbox/{Thread,QuickReplyMenu,MessageBubble}.tsx`, settings and auth pages, `public/offline.html`, `components/Shell.tsx` | **Modify.** Headings, landmarks, the live thread, the menu's options |
| `apps/web/app/globals.css`, `scripts/check-logical-css.mjs` | **Modify.** Focus, motion, letter-spacing; `space-x-*` joins the banned classes |
| `apps/web/components/inbox/TemplatePicker.tsx`, `Composer.tsx` | **Create / Modify.** A template when the window is closed |

---

## Task C1: Times in the reader's language

**Files:**
- Modify: `apps/web/lib/format.ts`, `apps/web/lib/format.test.ts`, and every caller of
  `formatDuration`, `formatRelative`, `formatUntil` and `formatDateTime` (17 files)

- [ ] **Step 1: Write the failing tests** — in `lib/format.test.ts`:

- "says a duration in the reader's units" — `formatDuration(2331, "ar")` is `"38 د 51 ث"`,
  `formatDuration(82800, "ar")` is `"23 س"`; English is unchanged: `"38m 51s"`, `"23h"`.
- "says an age in the reader's units" — under a minute is `"الآن"` in Arabic and `"<1m"` in
  English; `"19 د"`, `"2 س"`, `"3 ي"`; past a week, the date in the reader's language.
- "says how long is left" — `formatUntil` in both, and `"0 د"` once it has passed.
- "keeps a date in the workspace's time and the reader's language" — unchanged from Part B, with
  the language now required.

- [ ] **Step 2: Run them and see them fail**

Run: `npm run test --workspace web -- lib/format.test.ts`
Expected: FAIL — the functions ignore a language.

- [ ] **Step 3: The formatters**

The language becomes a required argument, second, so that `tsc` names every caller that has not
been given one — an optional one would leave English wherever nobody looked:

```ts
type Locale = "en" | "ar";

// Arabic abbreviates a unit to its first letter, as WhatsApp does: دقيقة، ساعة، ثانية، يوم.
const UNITS = {
  en: { s: "s", m: "m", h: "h", d: "d", gap: "" },
  ar: { s: "ث", m: "د", h: "س", d: "ي", gap: " " },
} as const;

const some = (n: number, unit: "s" | "m" | "h" | "d", locale: Locale) =>
  `${n}${UNITS[locale].gap}${UNITS[locale][unit]}`;

export function formatDuration(seconds: number, locale: Locale): string {
  if (seconds < 60) return some(Math.round(seconds), "s", locale);
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) {
    const rest = Math.round(seconds % 60);
    return rest ? `${some(minutes, "m", locale)} ${some(rest, "s", locale)}` : some(minutes, "m", locale);
  }
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${some(hours, "h", locale)} ${some(rest, "m", locale)}` : some(hours, "h", locale);
}

/** Compact age for lists: "<1m", "3m", "2h", "5d", then a date. */
export function formatRelative(iso: string, locale: Locale, now: Date = new Date()): string {
  const seconds = Math.max(0, (now.getTime() - new Date(iso).getTime()) / 1000);
  // Not "<1 د": a sign beside Arabic is mirrored, and reads as more than a minute.
  if (seconds < 60) return locale === "ar" ? "الآن" : "<1m";
  if (seconds < 3600) return some(Math.floor(seconds / 60), "m", locale);
  if (seconds < 86400) return some(Math.floor(seconds / 3600), "h", locale);
  if (seconds < 7 * 86400) return some(Math.floor(seconds / 86400), "d", locale);
  return new Date(iso).toLocaleDateString(DATE_LOCALE[locale], { day: "numeric", month: "short" });
}
```

`formatUntil(iso, locale, now)` and `formatDateTime(iso, timeZone, locale)` follow, the language
required in both. Each caller takes `useLocale()`; `LeadDrawer` also stops assuming Dubai and
reads the workspace's time zone from `useMe()`, as `InviteForm` does.

- [ ] **Step 4: Run the checks**

Run: `npm run check --workspace web`
Expected: PASS — `tsc` having named every caller on the way.

- [ ] **Step 5: Commit**

```bash
git add apps/web/lib/format.ts apps/web/lib/format.test.ts apps/web/app apps/web/components
git commit -m "feat(web): durations, ages and dates in the reader's language"
```

(The commit names the changed files one by one, as every commit here does; the two folders above
stand for the seventeen callers.)

---

## Task C2: Text that keeps its own direction

**Files:**
- Create: `apps/web/components/Bidi.tsx`, `apps/web/components/Bidi.test.tsx`
- Modify: `components/inbox/{MessageBubble,ConversationRow,Thread,QuickReplyMenu,DraftPanel}.tsx`,
  `components/crm/{CustomerRow,CustomerPanel,LeadCard,LeadDrawer,TaskRow,Timeline,ScoreReasons,MergeDialog,BoardColumn}.tsx`,
  `components/settings/QuickReplySettings.tsx`, `app/[tenant]/customers/[contactId]/page.tsx`,
  `app/[tenant]/today/page.tsx`
- Test: the component tests beside each, where one exists

- [ ] **Step 1: Write the failing tests**

`components/Bidi.test.tsx`:

- "`Ltr` keeps a number the way it is written" — renders `dir="ltr"` and tabular figures around
  `+971500000104`.
- "`Auto` lets what a person wrote choose its direction" — renders `dir="auto"`.

Beside the components (one assertion each, in the test file that already exists):

- `MessageBubble` — a message's text is inside an element with `dir="auto"`.
- `ConversationRow` — the name and the preview each have `dir="auto"`; the preview's "You:" is
  outside the element that holds the customer's words.
- `CustomerRow`, `CustomerPanel` — the phone number has `dir="ltr"`.
- `TaskRow` — the title has `dir="auto"`.
- `ScoreReasons` — `+10` has `dir="ltr"`.
- `Thread` — the back link's arrow carries `rtl:-scale-x-100`.

- [ ] **Step 2: Run them and see them fail**

Run: `npm run test --workspace web -- components`
Expected: FAIL.

- [ ] **Step 3: The two components, then every place the audit named**

`components/Bidi.tsx`:

```tsx
import type { ReactNode } from "react";

/**
 * What is a number stays the way it is written — a phone number, a price, a
 * score — whatever the language around it ([07] § 6). Without this an Arabic
 * line moves the plus sign of +971… to the other end.
 */
export function Ltr({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <span dir="ltr" className={`tabular-nums ${className}`}>
      {children}
    </span>
  );
}

/**
 * What a person wrote chooses its own direction: a name, a message, a title.
 * On the element that truncates, so a Latin name in an Arabic line loses its
 * end and not its beginning.
 */
export function Auto({
  children,
  className = "",
  as: Tag = "span",
}: {
  children: ReactNode;
  className?: string;
  as?: "span" | "p" | "div";
}) {
  return (
    <Tag dir="auto" className={className}>
      {children}
    </Tag>
  );
}
```

Then, by rule rather than by screen:

- **A person's words** — message bodies, previews, timeline entries, notes, names, task and lead
  titles, car names — `Auto`, on the element that carries `truncate` where there is one.
- **Numbers** — phone numbers, identities, money, scores, percentages — `Ltr`.
- **Two things side by side** get a `gap-*` on their parent, never `ms-*` on one of them: an
  element with its own direction has its own idea of which side is the start.
- **Arrows that mean a direction** — the back link — carry `rtl:-scale-x-100`. The timeline's
  in-and-out arrows become ↙ and ↗, which mean the same in both directions.

- [ ] **Step 4: Run the checks, and look**

Run: `npm run check --workspace web`, then re-run the audit's screenshots for the inbox, a French
thread, the customers list, the customer page, the tasks and the quick replies.
Expected: PASS; each of the six rows of the audit table above reads right.

- [ ] **Step 5: Commit**

```bash
git commit -m "fix(web): what a person wrote keeps its direction, and a number stays a number"
```

---

## Task C3: Words instead of codes, and counts that read right

**Files:**
- Create: `apps/web/lib/words.ts`, `apps/web/lib/words.test.ts`
- Modify: `apps/web/messages/{en,ar}.ts`, `components/settings/{ChannelSettings,TeamSettings,KnowledgeSettings}.tsx`,
  `components/crm/{LeadDrawer,LeadCard,ProfileField,ScoreReasons}.tsx`,
  `components/inbox/DraftPanel.tsx`, `app/[tenant]/today/page.tsx`

- [ ] **Step 1: Write the failing tests**

`lib/words.test.ts`:

- "says a stored code in the reader's language" — `word(t, "channel.status", "connected")` is the
  catalogue's `channel.status.connected`.
- "shows a code nobody has a word for, rather than nothing" — an unknown value comes back as it is.
- "counts the Arabic way" — `counted("ar", 1, "people")` is `"شخص واحد"`, 2 `"شخصان"`, 3
  `"3 أشخاص"`, 11 `"11 شخصًا"`, 100 `"100 شخص"`; English is `"1 person"`, `"3 people"`.

Component tests: Channels shows "متصل" and "معتمد" in Arabic; the lead drawer's source is
"واتساب"; a profile's `local` is "محلي"; a score reason with a known `signal` is said from the
catalogue and an unknown one falls back to the API's label.

- [ ] **Step 2: Run them and see them fail**

Run: `npm run test --workspace web -- lib/words.test.ts components`
Expected: FAIL.

- [ ] **Step 3: `lib/words.ts`**

```ts
import { ar } from "@/messages/ar";
import { en } from "@/messages/en";
import type { Locale, MessageKey } from "@/lib/i18n";

/**
 * A value the API stores as a code — a status, a source, a category — as a
 * word. One that has no word yet is shown as it is: a new status from Meta
 * must not become a blank.
 */
export function word(t: (key: MessageKey) => string, group: string, value: string): string {
  const key = `${group}.${value.toLowerCase()}`;
  return key in en ? t(key as MessageKey) : value;
}

const NOUNS = {
  people: { en: ["person", "people"], ar: ["شخص واحد", "شخصان", "أشخاص", "شخصًا", "شخص"] },
  days: { en: ["day", "days"], ar: ["يوم واحد", "يومان", "أيام", "يومًا", "يوم"] },
  passages: { en: ["passage", "passages"], ar: ["مقطع واحد", "مقطعان", "مقاطع", "مقطعًا", "مقطع"] },
} as const;

/** A count with its noun. Arabic has a form for one, for two, for three to ten,
 *  for eleven to ninety-nine, and for the hundreds; `Intl.PluralRules` knows which. */
export function counted(locale: Locale, n: number, noun: keyof typeof NOUNS): string {
  if (locale === "en") return `${n} ${NOUNS[noun].en[n === 1 ? 0 : 1]}`;
  const [one, two, few, many, other] = NOUNS[noun].ar;
  const form = new Intl.PluralRules("ar").select(n);
  if (form === "one") return one;
  if (form === "two") return two;
  return `${n} ${form === "few" ? few : form === "many" ? many : other}`;
}
```

The catalogue gains `channel.status.*`, `template.status.*`, `template.category.*`,
`lead.source.*`, `profile.purchase_type.*`, `profile.payment.*`, `score.<signal>` for each signal
in `sales/scoring.py`, and `draft.blocked.<guard>` for each guard; `today.hello` takes the comma
into the string, so Arabic has its own.

- [ ] **Step 4: Run the checks**

Run: `npm run check --workspace web`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(web): a stored code is said as a word, and Arabic counts take their forms"
```

---

## Task C4: The server learns the reader's language

**Files:**
- Create: `supabase/migrations/0015_sales_reader_language.sql`
- Modify: `apps/api/src/dealerai/routes/me.py`, `apps/web/lib/api/{client,hooks}.ts`,
  `apps/web/lib/api.ts`, `apps/web/app/[tenant]/providers.tsx`
- Test: `apps/api/tests/test_reader_language.py`, `apps/web/lib/api/client.test.ts`

- [ ] **Step 1: Write the failing tests**

`tests/test_reader_language.py`:

- `test_a_person_reads_english_until_they_say_otherwise` — `/v1/me` has `locale: "en"`.
- `test_a_person_says_what_they_read` — `PUT /v1/me/locale {"locale": "ar"}` → 204; `/v1/me` has
  `"ar"`; nobody else's changed.
- `test_only_a_language_the_app_speaks` — `"fr"` → 400.
- `test_somebody_with_no_profile_yet_gets_one` — a user with no `profiles` row: the PUT creates it.

`lib/api/client.test.ts`: "every request says what language its reader is using" — the client
sends `Accept-Language` from the document's language.

- [ ] **Step 2: Run them and see them fail**

Run: `uv run pytest tests/test_reader_language.py -q` (scratch database)
Expected: FAIL — `locale` is not a column, and the route does not exist.

- [ ] **Step 3: The migration, the route, the header**

`0015_sales_reader_language.sql`:

```sql
-- =============================================================================
-- 0015_sales_reader_language — S7 Part C.
-- What language a person reads the app in. The browser has always known; the
-- server needs it for what it writes when nobody is there to ask: a
-- notification, and the push that follows it.
-- =============================================================================

alter table profiles
  add column locale text not null default 'en' check (locale in ('en', 'ar'));

-- A person sets their own, and only their own. Definer, because profiles are
-- written through functions (0013) and somebody new may not have a row yet.
create or replace function app.set_locale(p_user uuid, p_locale text)
returns void
language sql
security definer
set search_path = public, pg_temp
as $$
    insert into profiles (id, locale) values (p_user, p_locale)
    on conflict (id) do update set locale = excluded.locale;
$$;

revoke all on function app.set_locale(uuid, text) from public;
grant execute on function app.set_locale(uuid, text) to dealerai_app;
```

`routes/me.py`: `locale` joins `MeOut`; `PUT /v1/me/locale` takes `{"locale": "en" | "ar"}` and
calls `app.set_locale` with the caller's own id.

The web: `createApiClient()` and the server-side `api()` add `Accept-Language`; `Providers` holds
one effect — when `/v1/me` says a different language from the one on screen, it tells the server.
That covers the toggle, a second device, and everybody who chose Arabic before today.

- [ ] **Step 4: Run them and see them pass**, then `npm run api-types`.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(sales): the server learns what language its reader reads"
```

---

## Task C5: A refusal in the reader's language

**Files:**
- Modify: `apps/api/src/dealerai/core/errors.py`, and the routes whose refusals a screen can cause:
  `inbox.py`, `tasks.py`, `leads.py`, `pipelines.py`, `quick_replies.py`, `team.py`, `tenants.py`,
  `settings.py`, `documents.py`, `suggestions.py`, `customers.py`, `push.py`
- Modify: `apps/web/components/auth/{LoginForm,SignupForm}.tsx`, `apps/web/messages/{en,ar}.ts`
- Test: `apps/api/tests/test_refusals_in_arabic.py`, `apps/web/components/auth/LoginForm.test.tsx`

- [ ] **Step 1: Write the failing tests**

`tests/test_refusals_in_arabic.py`:

- `test_a_refusal_is_said_in_the_readers_language` — deleting a stage that holds a lead with
  `Accept-Language: ar` → 409 whose `detail` is Arabic and names the stage and the count; without
  the header, the English sentence, unchanged.
- `test_a_refusal_with_no_arabic_yet_is_still_said` — an `AppError` raised without `ar=` answers
  an Arabic reader in English rather than with nothing.
- `test_every_refusal_a_screen_can_cause_has_arabic` — the contract: in the route modules named
  above, every `raise` of a refusal a person can cause passes `ar=`. A scan of the source, as
  `test_import_contracts.py` scans for `emit(`; cursors, internal lookups and `NotFound` are
  developer-facing and exempt, each exemption on a list in the test with its reason.
- `test_an_invalid_form_is_refused_in_arabic_too` — a 400 from validation carries an Arabic detail.

- [ ] **Step 2: Run them and see them fail**

Expected: FAIL — the detail is English either way.

- [ ] **Step 3: The error, the handler, the sentences**

`core/errors.py`:

```python
class AppError(Exception):
    ...
    def __init__(
        self,
        detail: str | None = None,
        *,
        errors: list[dict[str, Any]] | None = None,
        ar: str | None = None,
    ) -> None:
        super().__init__(detail or self.title)
        self.detail = detail
        self.errors = errors or []
        #: The same sentence for somebody reading the app in Arabic. Beside the
        #: English one, where whoever changes the one sees the other.
        self.ar = ar


def reads_arabic(request: Request) -> bool:
    """What the browser says its reader is using (apps/web sends the UI's language)."""
    return request.headers.get("Accept-Language", "").strip().lower().startswith("ar")
```

`_app_error` answers `exc.ar if exc.ar and reads_arabic(request) else exc.detail`; `_validation`
has one Arabic sentence of its own. Then each refusal a screen can cause gains its `ar=`, written
by the same f-string rules as its English, so a count or a name is in both:

```python
raise StageInUse(
    f"{name} still holds {held} {'lead' if held == 1 else 'leads'}. Move them first.",
    ar=f"ما زالت مرحلة «{name}» تضم {held} من الفرص. انقلها أولًا.",
)
```

Sign-in: `LoginForm` and `SignupForm` say `auth.failed` — one sentence of ours, in both languages
— in place of Supabase's. It was never meant to say more than that
([08](../08-screens.md) §14).

- [ ] **Step 4: Run them and see them pass**

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(sales): a refusal is said in the language of whoever it refuses"
```

---

## Task C6: Notifications in the reader's language

**Files:**
- Modify: `apps/api/src/dealerai/events/handlers/{notify,inbox,crm,copilot,manager}.py`
- Test: `apps/api/tests/test_notifications_in_arabic.py`

- [ ] **Step 1: Write the failing tests**

- `test_an_arabic_reader_is_told_in_arabic` — SALES_1's `profiles.locale` is `ar`: an assignment
  writes an Arabic title; SALES_2, reading English, gets the English one from the same code.
- `test_the_push_carries_the_same_words` — the pushed title, opened with the phone's key, is the
  Arabic one.
- `test_a_name_stays_a_name` — "{customer} is yours now" in Arabic still holds the customer's name
  as written.
- `test_the_brief_arrives_with_its_arabic_headline` — `brief_ready` for an Arabic reader carries
  `headline["ar"]`.
- `test_every_notification_has_both` — the contract: every `notify(` call site passes words in both
  languages, or a value that is data in either (a customer's name, a task's title).

- [ ] **Step 2: Run them and see them fail**

- [ ] **Step 3: Both languages at the call site, the reader's chosen on insert**

`events/handlers/notify.py`:

```python
class Words(NamedTuple):
    """One thing to tell somebody, in each language the app speaks."""

    en: str
    ar: str


def same(text: str | None) -> Words | None:
    """What is data in either language: a customer's name, a task's title."""
    return Words(text, text) if text else None
```

`notify()` takes `title: Words` and `body: Words | None`, and the insert chooses with the row it
is already writing for — no second query:

```sql
insert into notifications (tenant_id, user_id, kind, title, body, href, entity, dedupe_key)
select $1, $2, $3,
       case when p.locale = 'ar' then $5 else $4 end,
       case when p.locale = 'ar' then $7 else $6 end,
       $8, $9, $10
  from (select 1) one left join profiles p on p.id = $2
on conflict do nothing
returning id
```

Every call site then says both: `Words("A customer is waiting for you", "عميل بانتظارك")`,
`Words(f"{customer} is yours now", f"{customer} أصبح من عملائك")`, and the table of fixed
sentences in `handlers/inbox.py` becomes a table of `Words`.

- [ ] **Step 4: Run them and see them pass**, with everything that notifies.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(sales): a notification is written in the language its reader reads"
```

---

## Task C7: Dialogs that behave like dialogs

**Files:**
- Create: `apps/web/components/Modal.tsx`, `apps/web/components/Modal.test.tsx`
- Modify: `components/crm/{EraseDialog,MergeDialog,ReassignDialog,LostReasonDialog,CustomerPanel,LeadDrawer}.tsx`,
  `components/NotificationsBell.tsx`

- [ ] **Step 1: Write the failing tests**

`components/Modal.test.tsx`:

- "opens as a modal and is named by its title" — `showModal()` is called; the dialog is labelled
  by its heading.
- "closes on Escape, and says so" — the dialog's `cancel` reaches `onClose`.
- "closes when its backdrop is pressed, not when its content is".
- "leaves the page when it is closed" — unmounting closes the dialog.

`NotificationsBell.test.tsx`: "closes on Escape and gives focus back to the bell".

- [ ] **Step 2: Run them and see them fail**

- [ ] **Step 3: `components/Modal.tsx`**

```tsx
"use client";

import { useEffect, useId, useRef, type ReactNode } from "react";

/**
 * A modal, on the platform's own: `<dialog>` and `showModal()` move focus in,
 * keep Tab inside, close on Escape and give focus back to whatever opened it
 * ([07] § 10) — none of which a `div` with `role="dialog"` does.
 */
export function Modal({
  title,
  onClose,
  children,
  className = "",
}: {
  title: ReactNode;
  onClose: () => void;
  children: ReactNode;
  className?: string;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const heading = useId();

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog || dialog.open) return;
    dialog.showModal();
    return () => dialog.close();
  }, []);

  return (
    <dialog
      ref={ref}
      aria-labelledby={heading}
      onCancel={(event) => {
        event.preventDefault(); // React owns whether it is open
        onClose();
      }}
      onClick={(event) => {
        if (event.target === ref.current) onClose(); // the backdrop, not the content
      }}
      className={`bg-surface text-foreground border-border m-auto w-[min(32rem,calc(100vw-2rem))] rounded-lg border p-4 backdrop:bg-black/40 ${className}`}
    >
      <h2 id={heading} className="text-base font-semibold">
        {title}
      </h2>
      {children}
    </dialog>
  );
}
```

The four dialogs lose their own overlay, `role` and positioning and render inside `Modal`. The
customer panel and the lead drawer use it too below `md`, where they cover the screen; from `md`
up the panel stays a column beside the thread, as it is. The bell is a menu, not a modal: it gains
Escape and returns focus to its button.

- [ ] **Step 4: Run the checks, and walk it with a keyboard**

Run: `npm run check --workspace web`; then in a browser: open Erase, Tab round it, Escape.
Expected: PASS; focus never leaves the dialog, and returns to the button that opened it.

- [ ] **Step 5: Commit**

```bash
git commit -m "fix(web): dialogs take focus, keep it, and give it back"
```

---

## Task C8: A page a screen reader can make sense of

**Files:**
- Modify: `components/inbox/{ConversationList,Thread,QuickReplyMenu}.tsx`,
  `app/[tenant]/settings/layout.tsx`, `components/auth/JoinInvitation.tsx`,
  `components/settings/ChannelSettings.tsx`, `components/Shell.tsx`, `public/offline.html`,
  `apps/web/messages/{en,ar}.ts`

- [ ] **Step 1: Write the failing tests**

- `ConversationList` — the inbox has an `h1` (visually hidden: the tabs already say where one is).
- `Thread` — the messages are a `log`, polite, named.
- `QuickReplyMenu` — an option holds no button; pressing the option picks it.
- settings layout — the "not part of your role" message is under an `h1`.
- `Shell` — the two navigations have different names ("Main", "Sections").
- `lib/sw.test.ts`'s neighbour: the offline page has a `main`.

- [ ] **Step 2: Run them and see them fail**

- [ ] **Step 3: The structure**

One `h1` per page; `h2` before `h3` on Channels; `aria-label` on each `nav`; the thread's list
`role="log" aria-live="polite" aria-relevant="additions"`; the quick-reply option is the control
itself — `role="option"`, `aria-selected`, `onMouseDown` — with no button inside it.

- [ ] **Step 4: Run the checks; run `axe` over the audit's pages again**

Expected: PASS; no violation of any impact on any audited state.

- [ ] **Step 5: Commit**

```bash
git commit -m "fix(web): a heading on every page, a thread that announces itself, one name per landmark"
```

---

## Task C9: Seeing it and touching it

**Files:**
- Modify: `apps/web/app/globals.css`, `apps/web/scripts/check-logical-css.mjs`,
  `components/inbox/{MessageBubble,Thread,DraftPanel}.tsx`, `components/LocaleToggle.tsx`,
  `components/manager/WaitingList.tsx`, `app/[tenant]/settings/layout.tsx`

- [ ] **Step 1: Write the failing tests**

- `scripts/check-logical-css.test.mjs` (or the script's own self-check): `space-x-4` is refused.
- `MessageBubble` — the time and the ticks do not use `text-muted` on a sent message.
- `WaitingList` — the name's element cannot shrink below a readable width.

- [ ] **Step 2: Run them and see them fail**

- [ ] **Step 3: The rules**

`globals.css`:

```css
/* One focus ring, the brand's, wherever the keyboard is. */
:focus-visible {
  outline: 2px solid var(--brand);
  outline-offset: 2px;
}

/* Arabic letters join; spacing them pulls words apart ([07] § 6). */
[dir="rtl"] [class*="tracking-"] {
  letter-spacing: normal;
}

@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
```

The back link and the source chips become 44 px targets; a sent message's time and ticks take the
bubble's own text colour at reduced opacity that still passes 4.5:1; the settings sections wrap
below `md` instead of scrolling, each on one line; a waiting customer's name keeps `min-w-24` and
the hand-over menu drops to its own line; and Knowledge's file chooser becomes a button of ours
over the browser's input, which still does the choosing.

- [ ] **Step 4: Run the checks; `axe` again; look at 375 px**

- [ ] **Step 5: Commit**

```bash
git commit -m "fix(web): contrast on a sent message, targets a thumb can hit, focus and motion"
```

---

## Task C10: A template when the window is closed

**Files:**
- Create: `apps/web/components/inbox/TemplatePicker.tsx`, `TemplatePicker.test.tsx`
- Modify: `apps/web/components/inbox/{Composer,Thread}.tsx`, `apps/web/messages/{en,ar}.ts`

- [ ] **Step 1: Write the failing tests**

- "offers the approved templates in the customer's language first" — French for a French customer;
  the others after; none that Meta has not approved.
- "shows what will be sent, with what was typed" — `{{1}}` and `{{2}}` filled as they are typed,
  the customer's first name already in the first.
- "does not send with a blank left in it".
- "sends the template and its variables" — `useSendMessage().mutate({ templateId, variables })`.
- "says a marketing template is a paid message".
- `Composer`: "offers a template in place of the text box when the window is closed" — and still
  offers an internal note.

- [ ] **Step 2: Run them and see them fail**

- [ ] **Step 3: The picker**

`useTemplates(channelId)` already reads them and `useSendMessage` already sends one; the picker is
a `select`, an input per variable, the preview in a bubble with `dir="auto"`, and Send. `Thread`
passes the conversation's `channel_id`, the customer's language and name.

- [ ] **Step 4: Run the checks, and send one**

In a browser, as Salem, to Karim, whose window is closed: pick `price_update` in French, fill it,
send; the message appears in the thread and in `psql` as a `template`.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(web): a template can be sent when the 24-hour window has closed"
```

---

## Task C11: The whole check, then every screen again

**Files:**
- Modify: `docs/sales/plans/s7-pilot-readiness.md` (a Part C review), `docs/sales/README.md`,
  `docs/sales/07-frontend.md` (§6 and §10, where the build now differs)

- [ ] **Step 1: The whole check** — on the scratch database.

Run: `npm run check && npm run check:openapi`
Expected: every suite green, the guards at 100%, no drift.

- [ ] **Step 2: The audit, again, and by hand**

1. The audit's 40 states in Arabic at 375 px: no sideways scroll, and `axe` reports nothing.
2. Each row of the audit table, looked at: a duration, an age, a date; a phone number; a French
   thread; a Latin name cut at its end; the quick replies; the back arrow; `+10`; the statuses on
   Channels; the lead's source; a count of people and of days.
3. In English, the same screens are unchanged.
4. A refusal, caused from a screen in Arabic, is Arabic — a stage that holds a lead; a shortcut
   that is taken.
5. An Arabic reader's notification is Arabic in the bell and in the push; an English reader's is
   English, from the same event.
6. With a keyboard only: sign in, open a conversation, send a quick reply, open and close the
   customer panel, erase a customer through the dialog, move a lead — and Escape leaves every
   dialog with focus back where it was.
7. With reduced motion asked for, nothing animates.
8. Salem sends Karim a template with the window closed.

- [ ] **Step 3: The review, and commit**

Append `## Part C review — <date>` in the shape of Part B's, with the audit's numbers before and
after.

```bash
git commit -m "docs(sales): S7 Part C, the Arabic and accessibility pass, with the run recorded"
```

---

## Spec coverage (Part C)

| Requirement | Task |
|---|---|
| [07](../07-frontend.md) §6 — customer content `dir="auto"` per message | C2 |
| §6 — prices, phone numbers, times in `dir="ltr"` with tabular figures | C1, C2 |
| §6 — Arabic never letter-spaced; long strings wrap rather than clip | C9 |
| §6 — `check:rtl` catches `space-x-*` | C9 |
| §10 — labels on icon-only buttons in both languages | Held already: `axe` found none unlabelled |
| §10 — visible focus; focus trapped and restored in dialogs | C9, C7 |
| §10 — the thread is a `log`, polite | C8 |
| §10 — colour never the only signal; reduced motion respected | Held already (response state and band carry text); C9 |
| §10 — the keyboard map | Not built: see above |
| [08](../08-screens.md) §4 — closed window: a template picker with a live preview and a paid-message hint | C10 |
| [08](../08-screens.md) §15.9 — accessibility and Arabic pass, §1–§13 revisited | C11 |
| S2 review — notification text in the reader's language | C4, C6 |
| S6 review — API refusals in Arabic; statuses as words; Arabic counts | C5, C3 |
| S4 review — `needs_human` and guard reasons in Arabic | Guard reasons: C3. What the model writes: not built, see above |

## Execution (Part C)

Inline in this session, as Parts A and B were — no subagents unless asked. Checkpoints after C3
(what the browser can fix alone), C6 (what needed the server), C10, and C11.

## Part C review — 2026-10-03

Eleven tasks, then every screen again: the same 40 states in Arabic at 375 px, the same 40 in
English, a day's work with the keyboard alone, and the server's own words read by an Arabic reader
and an English one from the same event. The findings the plan fixed are in its table above; these
are what building it and running it found besides.

| Found | Why it mattered | Fixed in |
|---|---|---|
| An upcoming task read "<1m" | An age is clamped at zero, so every task not yet due said so — and would have said "now" in Arabic. A due time has its own formatter, which says how far ahead it is: "in 3h" | `71dc388` |
| A flag is made of left-to-right characters | Inside `dir="auto"` the flag is the first thing read, and it turned an Arabic customer's name left to right. `CustomerName` keeps it outside | `3d13072` |
| `dir="ltr"` or `dir="auto"` on a line of its own moves the line | A phone number or a Latin title jumped to the left edge of an Arabic screen. The direction goes on a span inside a line that still starts where the page does | `3d13072`, `e5e6b92` |
| The thread's own lines and the list's previews were English the API wrote | "Assigned to Sara", "Voice note": the seeded threads had none, so the audit never met them. An event keeps the name beside its sentence and a preview with no words is empty; the screen says both | `2364c77` |
| Why a draft was held back was a sentence, not a code | The screen could not say it in Arabic. It is stored as `check: detail`, and a draft the model simply did not produce has no reason at all | `2364c77` |
| A notification that begins with a Latin name read backwards | "James Whitfield أصبح من عملائك" was laid out left to right. No test showed it; handing a customer to an Arabic reader did. Names are wrapped in Unicode isolates and the bell reads sentences with `unicode-bidi: plaintext` — `dir="auto"` takes the first letter even inside an isolate | `6625824` |
| React runs an effect's cleanup after the dialog has left the page | Closing it then gives focus back to nothing. The modal closes in a layout effect's cleanup, while it is still there | `234dc64` |
| jsdom has `<dialog>` and none of its behaviour | Every test of a dialog would have seen a closed one. A setup file opens and closes it; focus is checked in a browser | `234dc64` |
| The inbox's list was a second `<aside>` | Two landmarks of one kind with no names. It is the page, so it is a `div`; and the log's role went on a wrapper, because a log is not a list | `2cae71c` |
| The amber "due soon" timer was 3.2 to 1 | It only shows while a customer is about to wait too long, so most runs never drew it | `e5e6b92` |
| On the dashboard the brief's rows put who and what in one element | The name decided the direction, and an Arabic reader lost the first word of the reason | `e5e6b92` |
| A template's first blank is not always a name | The plan prefilled it with the customer's. In "The {{1}} is available" that is the car. Only a blank followed by a comma is taken for a greeting | `603a355` |
| 37 presses of Tab to reach the first conversation on a desk | Measured by the keyboard walk. A skip link is the first stop now: one press, Enter, four more | with this review |
| In English the thread's header still cut the customer's name at 375 px | "Omar Al Mazr…": the two buttons took what the timer had given back. They are narrower on a phone | with this review |

Different from the plan, on purpose: a due time has its own `formatDue`, because an age must never
run ahead — a message from a phone whose clock is two minutes fast was not sent "in 2m"; the
catalogue's new groups follow the ones already there (`channels.status.*`, `source.*`); `Words`
lives in `core/words.py`, shared by refusals and notifications, with `same()` for what is data in
either language; a 404 answers an Arabic reader with one general sentence rather than staying
exempt; the lead drawer is a dialog at every width and the customer panel only below `lg`, which
needs `lib/media.ts`; C3 made three small changes to the API although the plan called it the
browser's alone; and the paid-message note is on every template, since outside the 24 hours every
template is charged, not only a marketing one.

Sound as built, and left alone: no catalogue string was missing; no screen scrolled sideways at
375 px before or after; icon-only buttons already had names in both languages; and response state
and lead band already said in words what their colours said.

Known and deliberately not changed in Part C:

- **What the model writes for the team is English** — a draft's "needs a person" line, action
  chips, the summary and next step, a follow-up's reason, and so the `followup_ready`
  notification's title and the titles of tasks the copilot creates. S4's decision. Making it the
  team's language is a setting, three prompts and the copilot's evals again: asked of the owner.
- **No screen reader was run.** `axe-core`, the accessibility tree and a keyboard are what was
  used. TalkBack and VoiceOver on real phones are Part D's, with the real push.
- A file that could not be read keeps its reason in English (`documents.error`, written by the
  worker once for everybody). A lead's history line is "New → Qualified": the names are the
  dealership's and the arrow does not mirror.
- A notification written before this part keeps the words it was written in, and an event written
  before it shows its English sentence.
- Somebody with two devices in two languages is written to in the language of the one opened last.
- Links inside a sentence are smaller than 44 px (a task's customer, "Create an account", "Open
  [section]"), and so are the buttons of the local sign-in page.
- The template picker does not fill in the car or the price.
- Not built, as planned: the keyboard map, web fonts, per-vehicle Arabic names, stage and team
  names in two languages, the Marketing screens.
- This run's database was on port 54432: after a restart Windows had reserved the range that holds
  54332. Nothing in the repository changed for it.

**The audit, before and after** — 40 states, Arabic, 375 px:

| | Before | After |
|---|---|---|
| States with an `axe-core` violation | 14, across 7 rules (page-has-heading-one, landmark-unique, heading-order, landmark-one-main, region, nested-interactive, color-contrast) | 0 — and 0 in English |
| Pages with no `h1` | 7 | 0 |
| Screens that scroll sideways | 0 | 0 |
| Dialogs that are modal, named, hold focus, close on Escape and give focus back | 0 of 4, and two sheets that were not dialogs | 6 of 6 |
| Controls under 44 px, outside a sentence and the local sign-in page | 15 kinds, the thread's back link at 12 × 20 | 0 |
| Presses of Tab to the first conversation, on a desk | 37 | 1, Enter, then 4 |

**Checks, final:** `npm run check` on the scratch database — 1,550 backend tests, the guards at
100% branch coverage, 322 web tests, types, lint and logical CSS; `npm run check:openapi` — no
drift.

**Verified end to end on 2026-10-03**, against a freshly seeded workspace:

1. The 40 states in Arabic at 375 px, as a salesperson, a manager, the owner and nobody: no
   sideways scroll, a heading on every page, and nothing from `axe-core`. The same 40 in English:
   the same, and the screens read as they did.
2. The audit table, row by row, in the screenshots: "تأخر الرد 22 د 41 ث", "22 د", "الآن",
   "بعد 1 س", a date that reads 01/10/2026 from the right; "+971500000104"; "Le prix pour Oran,
   tout compris ?" with its question mark at its end; "Omar Al Maz…" cut where it ends; a back
   arrow that points back; "+10"; "التشغيل المشترك · متصلة" and "خدمي · معتمد"; "واتساب";
   "3 أشخاص", "5 مقاطع", "0 يوم هنا"; "صباح الخير، Ahmed".
3. A refusal caused from a screen in Arabic: removing a stage that holds a lead said "ما زالت مرحلة
   «New» تضم فرصة واحدة. انقلها أولًا.", and a shortcut already taken "الاختصار /price مستخدم في رد
   سريع آخر." The same two in English, to an English reader.
4. The app opened in Arabic told the server once (`PUT /v1/me/locale`) and not again on the next
   load; `profiles.locale` read `ar` for that person and `en` for the rest.
5. With the worker running, Sara handed one customer to Ahmed, who reads Arabic, and one to
   Mohamed, who reads English. Ahmed's bell: "Omar Al Mazrouei أصبح من عملائك", "سلّمه إليك Sara
   Mansour", the name on the right where the sentence starts. Mohamed's: "Priya Nair is yours now",
   "Handed over by Sara Mansour". One waiting customer was "… بانتظار الرد" to Ahmed and "… is
   waiting" to Sara, from one event.
6. A task fell due for each of them. The stand-in for a push service checked the signature and
   opened both: "حان موعدها: Call Omar about the passport copy" on Ahmed's device, "Due now: Call
   Omar about the passport copy" on Mohamed's.
7. With a keyboard only, in Arabic on a desk: signed in; opened Omar's conversation; typed `/pr`,
   Enter put the quick reply in the box in his language with his name, Enter sent it; opened and
   closed the customer panel; moved James's lead from New to Contacted with the arrow key; and, as
   the owner, opened Erase, left it with Escape — focus back on the button — opened it again, typed
   the customer's name, and erased them. Each of the six dialogs, walked on its own: modal, named,
   focus inside on opening, fourteen Tabs that never reached the page behind, Escape, and focus
   back on what opened it. The bell closed on Escape and took focus back.
8. With reduced motion asked for, no element had a transition or an animation longer than a
   millisecond. Focus drew a 2 px ring in the brand's colour, on a phone and on a desk.
9. As Salem, to Karim, whose window had closed: the reply box was gone and the picker offered
   French first; `price_update` came with "Karim" in its first blank; Send stayed off until the
   other two were filled; the preview read "Bonjour Karim, le prix de Toyota Hilux 2.8 est
   maintenant AED 128,000."; and the row was there as a `template`, queued. A note for colleagues
   could still be written.

---
