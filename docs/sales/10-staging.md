# Sales — the staging day

Staging is the API, the worker and the web app running somewhere other than a laptop, against a
Supabase project of their own, with real accounts and no customers. It is where a real person
signs in for the first time, and where a phone is first told something.

This page is the order to do it in. Every step says who does it and how to tell it worked. The
founder's steps are dashboards and decisions; the rest is two commands. **No secret is ever pasted
into a chat, an issue or a commit** — each goes from where it was made straight into the place
that needs it.

**Where it stands (2026-10-05):** §2.1 to §2.3 are done — the project exists
(`sqlshcesowlrmhiugnpf`) and the schema is on it. Nothing after that has been run. The code's
half was built and checked on a laptop in S7 Part D ([review](plans/s7-pilot-readiness.md)); the
first run of this whole page is that part's second exit.

---

## 1. What has been decided, and what has not

| Decision | Where it stands |
|---|---|
| **Where the Supabase project lives** | **Mumbai (`ap-south-1`), on Supabase's Free plan — decided 2026-10-05.** The project earlier docs named is gone, so nothing has to be moved; [00](00-prd.md) §12 Q1 proposed Mumbai because Tokyo added 150–200 ms to every request from the UAE, and Supabase offers no region nearer the Gulf. Free is a plan of an *organisation*: the existing one is on Pro, where every project is 10 US dollars a month, so staging gets an organisation of its own (§2). What free costs instead is below. **The project that was made on 2026-10-05 is in Singapore (`ap-southeast-1`), not Mumbai** — found by which pooler answered for it. Measured from the owner's machine that day, by how long a connection takes to open: Mumbai about 50 ms away, Singapore about 100, Tokyo about 175. A region cannot be changed afterwards, only chosen again with a new project; which it is to be is the owner's call, and `fly.toml`'s region follows it |
| **Where the API and the worker run** | **Fly.io, in Mumbai (`bom`) — decided 2026-10-05.** Fly has no free plan: a card is needed, and a machine is paid for by the second while it runs — about 2.19 US dollars a month for the smallest, always on, in Fly's cheapest regions (its price list, read 2026-10-05; some regions cost more), and almost nothing while stopped. Two machines, so about 4.40 a month, or less if staging is stopped between the days it is used. What any host had to give: a container image run twice, in a region beside the database, a process that is never put to sleep — a webhook has to be answered, and the worker has no visitors to wake it — and a response that may stay open, which is how a screen hears about a new message. [`fly.toml`](../../fly.toml) says all of that; §4 is the commands |
| **Where the web app runs** | Vercel, as the architecture says |
| **Who sends the email** | **Not decided.** Supabase's own sender is for trying things: a few emails an hour, to the project's own team. A real sender is an account with an email service (Resend, Postmark, Amazon SES, …) and a domain it may send from. Until there is one, §7 can be walked by the project's own team and nobody else |

**What a free project costs instead of money.** Supabase pauses a Free project that has had too
little database activity for a week, after an email warning; a paused project can be resumed for
90 days, and after that it cannot. While staging's worker runs, it asks the database for work every
second, which should be activity enough — so the risk is stopping staging's machines for more than
a week and forgetting the project. It also has no backups, and a small database. All of that is
right for staging and wrong for customers: **the pilot's project is on a paid plan.**

## 2. The project (founder, then one command)

1. In the Supabase dashboard, make a **new organisation on the Free plan**, and in it the
   project: region Mumbai (`ap-south-1`). Note its address, `https://<project-ref>.supabase.co`.
   Not in the existing organisation: that one is on Pro, where a project is 10 US dollars a
   month. An account has two free projects.
2. Copy `.env.staging.example` to `.env.staging` and fill in the **session pooler** address, with
   the database password, from the project's *Connect* panel. The file is gitignored. Two things
   went wrong here the first time, and both look the same from outside — a connection that fails:
   - *Connect* offers three addresses. The **direct** one (`db.<project-ref>.supabase.co`) is
     reachable over IPv6 only, which most offices and homes do not have. It has to be the one
     labelled *Session pooler*: its host ends in `.pooler.supabase.com`, and its user is
     `postgres.<project-ref>`.
   - A password is part of an address, and an address cannot hold every character: `#`, `@`, `/`,
     `?` and `:` each have to be written as a percent code (`#` is `%23`). Easier is a password
     of letters and digits, which is what Supabase generates.
3. Apply the schema, from a laptop:

   ```bash
   npm run db:migrate:staging
   ```

   Every migration from `0001` is applied in order; `0000_local_shim.sql` is skipped, because
   Supabase already has what it stands in for. On 2026-10-05 all fifteen, `0001` to `0015`, went
   onto a new project in one run — the first time `0006` onward had met a hosted one. Afterwards,
   asked from outside: row-level security is on, and forced, on every table but three — `events`
   and `webhook_deliveries`, which the worker takes from before it knows whose they are, and
   `schema_migrations`; the public key's
   roles hold no privilege on any table; and `dealerai_app` exists, cannot yet sign in, and cannot
   bypass row-level security. If a migration ever fails here, stop: that is a finding, not
   something to work around.
4. Give the application its own way in — the one statement that is not in version control,
   because it carries a secret. In the SQL editor, with a password made for the purpose:

   ```sql
   alter role dealerai_app login password '<a new password, kept in the host's secrets>';
   ```

5. Read the project's security advisor once. It should name the three tables above, which the
   public key cannot reach, and the `vector` extension living in `public`. Anything else is news.
6. **Leave the API's exposed schemas as they are.** The `app` schema holds the functions that
   row-level security is written with, and the public key's roles may still call some of them —
   left from the days the browser read tables itself. They are out of reach only because the
   Data API does not serve that schema.

*How to tell:* the migration command ends with `ok` or `apply … done` on every line.

## 3. Authentication (founder)

In the project's Authentication settings:

1. **URL configuration.** Site URL: the web app's address, `https://<web>`. Redirect URLs: add
   `https://<web>/**`.
2. **Email templates.** Two links change, so that an email opens in whichever browser its reader
   taps it in — somebody who signs up in the installed app reads their mail somewhere else:

   | Template | Replace `{{ .ConfirmationURL }}` with |
   |---|---|
   | Confirm sign up | `{{ .RedirectTo }}&token_hash={{ .TokenHash }}&type=email` |
   | Reset password | `{{ .RedirectTo }}&token_hash={{ .TokenHash }}&type=recovery` |

   Until they are changed, both links still work — in the browser that asked, and nowhere else.
3. **SMTP.** The email service's host, port, user and password, and the address to send from.
4. **Google.** In Google Cloud, an OAuth client of type *Web application* whose authorised
   redirect URI is `https://<project-ref>.supabase.co/auth/v1/callback`; its id and secret go into
   the Google provider here.

*How to tell:* `https://<project-ref>.supabase.co/auth/v1/.well-known/jwks.json` answers with at
least one key. A project made today signs sessions with a private key and publishes the public
half there, and that is the only kind of session the API accepts outside a laptop. An empty list
means the project still signs with a shared secret: migrate it to signing keys in its JWT
settings. (`npm run smoke` checks this.)

## 4. The API and the worker (Fly.io)

One image, built from the repository's root, run twice. Fly builds it itself from
[`fly.toml`](../../fly.toml); to build it by hand:

```bash
docker build -f apps/api/Dockerfile -t dealerai-api .
```

| Process | Command | Needs |
|---|---|---|
| API | the image's default: `uvicorn dealerai.main:app --host 0.0.0.0 --port 8000` | Port 8000 behind HTTPS; `/internal/health` as its health check; never asleep |
| Worker | `python -m dealerai.worker` | No port; never asleep; one copy to begin with |

Both take the same settings. A secret goes into the host's own store for secrets, never into a
file in the repository:

| Variable | What it is | Where its value comes from |
|---|---|---|
| `ENV` | `staging` | — |
| `DATABASE_URL` | How the application reaches Postgres, as `dealerai_app` — never as `postgres` | The **session pooler** address (port 5432) from *Connect*, with the user `dealerai_app.<project-ref>` and the password from §2.4. Secret |
| `SUPABASE_URL` | The project's address | §2.1 |
| `SUPABASE_JWT_SECRET` | Signs invitation links and the links to customers' media. Not Supabase's: this deployment's own | 32 characters or more, made for the purpose (`openssl rand -hex 32`). Secret |
| `WEB_ORIGINS` | Who may call the API from a browser | The web app's address, `https://<web>` |
| `GOOGLE_API_KEY` | The model, for drafts, summaries and the brief | A Gemini key. Secret. Without it the app runs and writes no drafts |
| `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT` | Push to phones | A key made for staging (below) — never a laptop's own. The subject is a real `mailto:` address: a push service writes to it. Secret |
| `LOG_LEVEL` | `info` | — |
| `DB_POOL_MAX` | `5`, in `fly.toml` | A Free project's database takes 60 connections in all, and Supabase's own services hold about ten of them with nothing happening (counted 2026-10-05). The API and the worker each keep up to this many, and the API one more to listen with |

A push key is 32 bytes on the curve browsers use. `npm run vapid:keys` writes one into a laptop's
`.env` and nowhere else; for staging, make one and send it down a pipe into the host's command for
setting a secret, so that it is never on a screen:

```bash
cd apps/api && uv run python -c "from cryptography.hazmat.primitives.asymmetric import ec; from dealerai.notifications.push import b64; print(b64(ec.generate_private_key(ec.SECP256R1()).private_numbers().private_value.to_bytes(32, 'big')))" | <the host's command that reads a secret from a pipe>
```

Not yet: `CREDENTIALS_KEYS` and the `WHATSAPP_*` settings (S5), and `SUPABASE_ANON_KEY` (media,
below). Never: `STORAGE_DIR`, `MIGRATION_DATABASE_URL`.

**A wrong setting is named when the process starts, and it does not start**: a missing project
address, a secret that is short or is the one from Supabase's documentation, `WEB_ORIGINS` still
naming localhost, the transaction pooler (`:6543`) where the session pooler belongs. Read the
first lines of the log.

### On Fly.io

`fly.toml` has not been deployed yet: its keys were read from Fly's reference on the day Fly was
chosen, and the first deploy is what proves them. In a terminal of your own — the account, the
card and the sign-in are yours:

```bash
pwsh -Command "iwr https://fly.io/install.ps1 -useb | iex"    # Fly's command-line tool, once
fly auth login                                                 # opens a browser
fly apps create dealerai-staging                               # or a name that is free: put it in fly.toml
```

Then the settings in the table above — all but `ENV`, `LOG_LEVEL` and `DB_POOL_MAX`, which are in
`fly.toml`.
`fly secrets import` reads `NAME=VALUE` lines from the keyboard, so nothing is in a command line,
a history or a chat. Paste the lines, then end the input (Ctrl+Z and Enter on Windows, Ctrl+D
elsewhere):

```bash
fly secrets import --stage
```

A secret that is made rather than copied need never be seen at all:

```bash
echo "SUPABASE_JWT_SECRET=$(openssl rand -hex 32)" | fly secrets import --stage
```

Then build and start it — one machine for each of the two processes:

```bash
fly deploy --ha=false
fly scale count api=1 worker=1     # if it made more
fly logs                           # a wrong setting is named in the first lines
```

The API is then at `https://<app>.fly.dev`: that is `<api>` everywhere on this page, and what
`NEXT_PUBLIC_API_URL` is set to in §5.

*How to tell:* `https://<api>/internal/health` answers
`{"status":"ok","env":"staging","database":"ok","queue":{"waiting":0,"oldest_seconds":0}}`.
With the worker stopped, `waiting` only grows.

## 5. The web app

A Vercel project on this repository, with `apps/web` as its root directory and Node 22.

| Variable | Value |
|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | The project's address |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | The project's publishable key — public by design; row-level security is what protects the data |
| `NEXT_PUBLIC_API_URL` | `https://<api>` |

Never `NEXT_PUBLIC_DEV_AUTH`: it is a laptop's sign-in, and a production build ignores it anyway.

## 6. Is it fit to use

From a laptop, after every deploy:

```bash
npm run smoke -- --api https://<api> --web https://<web> --supabase https://<project-ref>.supabase.co
```

Twelve questions, each a read; none carries a credential. It ends with `fit to use`, or with what
to fix, by name: an API that thinks it is a laptop, a queue nobody is working, a local sign-in left
reachable, a web address the API does not allow, a project that publishes no keys.

## 7. The first sign-in, and two phones

The part no test can do. One person, then a second, with a phone each:

1. **Sign up** at `https://<web>/signup` with an email address and a password.
   *The email arrives, from the sender set up in §3.*
2. **Open the link on a phone**, from the mail app. *It lands on "Create your workspace", signed
   in — not on "that link has expired".*
3. **Create the workspace.** *It opens on Team and roles, with you as its owner.*
4. **Invite a second person** from that screen, into a team, and send them the link.
   *They sign up with the invited address, come back to the invitation, join, and are in the
   inbox with that role.*
5. **Sign in with Google**, as either of them. *The same account, not a second one.*
6. **Forget a password.** *The link from the email opens "Choose a new password"; the new one
   signs in.*
7. **Install the app** — Add to Home Screen, on an Android phone and on an iPhone — and turn
   notifications on for each in Settings → Notifications. *"Send a test notification" arrives on
   both.*
8. **Add a task due in two minutes.** *The bell shows it when it falls due, and the phone is told
   with the app closed. That is the worker.*
9. **With the screen reader on** — TalkBack, then VoiceOver — open the inbox, a page of settings,
   and a dialog. *Each says what it is, and can be left.*
10. **Read the page in Arabic**, on the phone.

Write down what happened under the Part D review in
[plans/s7-pilot-readiness.md](plans/s7-pilot-readiness.md): what worked, and the exact words of
anything that did not.

## 8. What staging cannot do yet

| What | Why | When |
|---|---|---|
| **Customers** | There is no WhatsApp number on it, and the seed refuses to run anywhere but a laptop — as it should: its first statement deletes a workspace | S5, with Meta's test number |
| **Voice notes, photos, documents** | The server reaches Storage with the project's public key, and nothing can tell it apart from anybody else holding that key. Customer media cannot be private that way. It needs a decision — Storage's own keys for a server, or a way of signing uploads — and then a task | Before staging receives its first voice note: S5's first task |
| **A link an email scanner has already opened** | Some mail systems open every link in a message to check it. The link is used up, and its reader is told it has expired. The cure is a page with a button between the email and the session. Not built | If it happens to somebody |
