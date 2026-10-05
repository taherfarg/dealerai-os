# Sales — the staging day

Staging is the API, the worker and the web app running somewhere other than a laptop, against a
Supabase project of their own, with real accounts and no customers. It is where a real person
signs in for the first time, and where a phone is first told something.

This page is the order to do it in. Every step says who does it and how to tell it worked. The
founder's steps are dashboards and decisions; the rest is two commands. **No secret is ever pasted
into a chat, an issue or a commit** — each goes from where it was made straight into the place
that needs it.

Nothing here has been done yet. The code's half was built and checked on a laptop in S7 Part D
([review](plans/s7-pilot-readiness.md)); the first run of this page is that part's second exit.

---

## 1. What has to be decided

| Decision | What is known |
|---|---|
| **Where the Supabase project lives** | The project earlier docs named is gone, so nothing has to be moved. [00](00-prd.md) §12 Q1 proposed Mumbai (`ap-south-1`): from the UAE, Tokyo added 150–200 ms to every request. If Supabase lists a region nearer the Gulf by now, that one |
| **Where the API and the worker run** | Any host that runs a container image, in a region beside the database, and that (a) never puts a process to sleep — a webhook has to be answered, and the worker has no visitors to wake it — and (b) lets a response stay open, which is how a screen hears about a new message. [../01-system-architecture.md](../01-system-architecture.md) §10 named Fly.io or Railway. Fly has regions in Mumbai and Tokyo both |
| **Where the web app runs** | Vercel, as the architecture says |
| **Who sends the email** | Supabase's own sender is for trying things: a few emails an hour, to the project's own team. A real sender is an account with an email service (Resend, Postmark, Amazon SES, …) and a domain it may send from |

## 2. The project (founder, then one command)

1. Create the Supabase project in the chosen region. Note its address,
   `https://<project-ref>.supabase.co`.
2. Copy `.env.staging.example` to `.env.staging` and fill in the **session pooler** address, with
   the database password, from the project's *Connect* panel. The file is gitignored.
3. Apply the schema, from a laptop:

   ```bash
   npm run db:migrate:staging
   ```

   Every migration from `0001` is applied in order; `0000_local_shim.sql` is skipped, because
   Supabase already has what it stands in for. **These migrations have never met a new Supabase
   project past `0005`.** If one fails, stop: that is a finding, not something to work around.
4. Give the application its own way in — the one statement that is not in version control,
   because it carries a secret. In the SQL editor, with a password made for the purpose:

   ```sql
   alter role dealerai_app login password '<a new password, kept in the host's secrets>';
   ```

5. Read the project's security advisor once. Every table should have row-level security on.

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

## 4. The API and the worker (founder picks the host)

One image, built from the repository's root, run twice:

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
