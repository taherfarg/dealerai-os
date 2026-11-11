# Sales — the staging day

Staging is the API, the worker and the web app running somewhere other than a laptop, against a
Supabase project of their own, with real accounts and no customers. It is where a real person
signs in for the first time, and where a phone is first told something.

This page is the order to do it in. Every step says who does it and how to tell it worked. The
founder's steps are dashboards and decisions; the rest is two commands. **No secret is ever pasted
into a chat, an issue or a commit** — each goes from where it was made straight into the place
that needs it.

**Where it stands (2026-10-06):** staging is deployed. §2, §4, §5 and §6 are done — the
project exists (`sqlshcesowlrmhiugnpf`) with the schema on it, the application signs in as
itself, the API with its worker and the web app are live on Render at
`https://dealerai-staging.onrender.com` and `https://dealerai-staging-web.onrender.com`, and the
check from outside passes twelve of twelve. Not done: authentication (§3), and the first sign-in
and the phones (§7) — nobody has signed in yet. The code's half was built and checked on a
laptop in S7 Part D ([review](plans/s7-pilot-readiness.md)); the first run of this whole page is
that part's second exit.

**The order on the day** is not quite the order of the sections. Render's form (§4) makes the
API and the web app (§5) together, and §2.4 is run while that form is open, because what it
makes is pasted there. Authentication (§3) comes after them, because it has to be told the web
app's address. Then the check (§6), and the first sign-in (§7).

---

## 1. What has been decided, and what has not

| Decision | Where it stands |
|---|---|
| **Where the Supabase project lives** | **Staging: Singapore (`ap-southeast-1`), on Supabase's Free plan. The pilot's project: Mumbai (`ap-south-1`).** Decided 2026-10-05. Mumbai is where customers' data is to live: [00](00-prd.md) §12 Q1 proposed it because Tokyo added 150–200 ms to every request from the UAE, Supabase offers no region nearer the Gulf, and the project earlier docs named is gone, so nothing has to be moved. The staging project was then made in Singapore — found by which pooler answered for it — and the owner chose to leave it there: a region cannot be changed afterwards, only chosen again with a new project, and staging holds no customers. Measured from the owner's machine that day, by how long a connection takes to open: Mumbai about 50 ms away, Singapore about 100, Tokyo about 175. Free is a plan of an *organisation*: the existing one is on Pro, where every project is 10 US dollars a month, so staging has an organisation of its own (§2). What free costs instead is below |
| **Where the API and the worker run** | **Staging: Render's free plan, in Singapore — decided 2026-10-05, when the owner asked for a host without a charge.** It costs nothing and needs no card. What it costs instead: the service is put to sleep after 15 minutes with no request and takes about a minute to wake; it has a tenth of a CPU; and it has no free background worker, so the API and the worker share one container ([`render.yaml`](../../render.yaml)). Koyeb's free plan was looked at too: Frankfurt or Washington only, a continent away from the database on every query. **The pilot, and staging if it must not sleep: Fly.io, beside the database** — decided 2026-10-05, Singapore (`sin`) for staging's database, Mumbai (`bom`) for the pilot's. Fly has no free plan: a card is needed, and a machine is paid for by the second while it runs — about 2.19 US dollars a month for the smallest, always on, in Fly's cheapest regions (its price list, read 2026-10-05; some regions cost more), and almost nothing while stopped. Two machines, so about 4.40 a month, or less if staging is stopped between the days it is used. What any host had to give: a container image run twice, in a region beside the database, a process that is never put to sleep — a webhook has to be answered, and the worker has no visitors to wake it — and a response that may stay open, which is how a screen hears about a new message. [`fly.toml`](../../fly.toml) says all of that; §4 is the commands |
| **Where the web app runs** | **Staging: Render's free plan, beside the API — decided 2026-10-06.** The architecture says Vercel, and Vercel's free plan is not for this: its fair-use page, read that day, keeps that plan for "non-commercial personal use only", and counts as commercial any deployment made for the gain of anyone who works on it. Its paid plan is 20 US dollars a month for each developer, and its trial is 14 days. Render's free plan says only not to run production on it, so the web app is a second free service in the same Blueprint (§5). What that costs: a page is rendered by a tenth of a CPU, the web app sleeps as the API does, and the two share the month's 750 hours. **The pilot's is not decided:** Vercel's paid plan, or the same two commands on Fly beside the API |
| **Who sends the email** | **Not decided.** Supabase's own sender is for trying things: a few emails an hour, to the project's own team. A real sender is an account with an email service (Resend, Postmark, Amazon SES, …) and a domain it may send from. Until there is one, §7 can be walked by the project's own team and nobody else |

**What a free project costs instead of money.** Supabase pauses a Free project that has had too
little database activity for a week, after an email warning; a paused project can be resumed for
90 days, and after that it cannot. While staging's worker runs, it asks the database for work every
second, which should be activity enough — so the risk is stopping staging's machines for more than
a week and forgetting the project. It also has no backups, and a small database. All of that is
right for staging and wrong for customers: **the pilot's project is on a paid plan.**

## 2. The project (founder, then one command)

1. In the Supabase dashboard, make a **new organisation on the Free plan**, and in it the
   project. Note its address, `https://<project-ref>.supabase.co`. The region is chosen once, on
   that screen, and the screen offers its own guess: staging's came out as Singapore
   (`ap-southeast-1`) and stays there; the pilot's is to be Mumbai (`ap-south-1`) — *South Asia
   (Mumbai)* in the list.
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
4. Give the application its own way in — the one step that is not a migration, because it makes
   a secret:

   ```bash
   npm run db:app-password:staging -- --clipboard
   ```

   It makes a password nobody chooses and nobody sees, sets it on `dealerai_app`, proves that
   it signs in, and puts the application's whole address on the clipboard, to be pasted where a
   host asks for `DATABASE_URL`. It is never printed. For a host whose command reads secrets from
   a pipe, leave `--clipboard` off and pipe it: the output is the one line `DATABASE_URL=…`. Run
   again, it makes another, and the one before stops working. (Typing `alter role … password
   '…'` into the SQL editor would work too, and would leave the password in the server's log;
   this sends only what the server stores.)

   **What went wrong here the first time** (2026-10-06): the command was not run. The address
   given to Render was the one already in `.env.staging` — the migration runner's, as
   `postgres` — and it works: the API answered, the worker worked the queue, and §6 passed
   twelve of twelve, with row-level security applying to nobody, because it does not apply to
   the database's owner. It was found by asking the database who was connected
   (`pg_stat_activity`), and put right within the hour. The API now refuses to start as
   `postgres` (§4), so the mistake says so by itself.

   **Nothing in this step needs to be looked at to be checked.** A box's contents were sent as
   a picture, and then an address was pasted into a conversation, to ask whether they were the
   right ones; both passwords were changed afterwards. Whether the right address is in place is
   the database's to say — it shows who is signed in — and the right one can be told by how it
   begins: `postgresql://dealerai_app`. The owner's password is changed on the project's
   *Database Settings* page, *Reset database password*, with a password the page generates;
   the new one then goes into `MIGRATION_DATABASE_URL` in `.env.staging`, and the application
   is not touched by any of it.

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
| `DATABASE_URL` | How the application reaches Postgres, as `dealerai_app` — never as `postgres` | Made whole by §2.4, and pasted or piped from there: the session pooler's address (port 5432) with the user `dealerai_app.<project-ref>`. Secret |
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
naming localhost, the transaction pooler (`:6543`) where the session pooler belongs, an address
that signs in as `postgres`. Read the first lines of the log.

### On Render, free

[`render.yaml`](../../render.yaml) is a Blueprint: Render reads it from the repository and makes
the two services it describes, the API with its worker and the web app (§5). It was first
applied on 2026-10-06 and came up as written: the file's field names held, both names were free,
and the two services answered at the addresses in step 3 within minutes. Before that the
container had been run here exactly as Render runs it, `python -m dealerai.both` with
`PORT=10000`: one process serving, the worker beside it and started again when it was killed,
137 MB in all.

1. A Render account — signing in with GitHub is enough, and no card is asked for.
2. **New → Blueprint**, this repository, and the branch `sales/phase-1` — the form offers
   `main`, where there is no `render.yaml`, and says so. Render then shows the two services and
   asks for the values the file leaves out:

   | Asked for | What to give |
   |---|---|
   | `DATABASE_URL` | Run §2.4's command with `--clipboard`, and paste. Secret. Not the address in `.env.staging`: that one is the owner's |
   | `NEXT_PUBLIC_SUPABASE_ANON_KEY` | The project's publishable key, copied from its *API Keys* page. Public by design |
   | `GOOGLE_API_KEY` | A Gemini key, or blank |
   | `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT` | A push key and a `mailto:` address, or both blank |

   `SUPABASE_JWT_SECRET` is not asked for: Render makes it, and nobody needs to see it. Nor are
   the two addresses: the file gives each service the other's, as Render will make them from
   the services' names.
3. The API is then at `https://dealerai-staging.onrender.com` and the web app at
   `https://dealerai-staging-web.onrender.com`. Those are `<api>` and `<web>` everywhere on this
   page. **If a name was taken, Render adds letters to it**, and each service has then been told
   a wrong address for the other: on its *Environment* page put `WEB_ORIGINS` right on the API
   and `NEXT_PUBLIC_API_URL` on the web app, and deploy both again. §6 names it when this has
   happened.

**What free means, day to day.** After 15 minutes with no request Render puts a service to
sleep, and with the API its worker: a task that falls due in that time is announced when the
service wakes. The first screen of the day takes about a minute, and may take two tries: the
web app wakes for the browser, and the API only for the web app's first question, so a first
page may say it could not load. Wait, and load it again. A month has 750 free hours for the two
services together. Both awake the whole time would use them in under sixteen days, and Render
then suspends both until the month ends — so nothing is set to keep staging awake. Asleep, the
worker asks the database for nothing, and Supabase pauses a Free project that has been quiet
for a week: open staging once a week, or resume the project from its dashboard. Render also
restarts a free service when it likes; nothing here minds.

A push that touches only `docs/` deploys nothing, and one that touches only the other
service's half deploys one of the two (`buildFilter` in the file).

It is right for staging and wrong for customers: a webhook has to be answered at once, and a
sleeping service cannot. The pilot's API is Fly's, below.

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

On Render, beside the API: a second free service in the same Blueprint, `dealerai-staging-web`,
built and started from the repository's root, where an npm workspace's packages are installed.

```bash
npm ci --include=dev && npm run build --workspace web
npm run start --workspace web
```

The build needs TypeScript and Tailwind, which are development packages, and a host that sets
`NODE_ENV=production` leaves those out unless they are asked for. `next start` listens on the
port Render names.

| Variable | Value |
|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | The project's address. In `render.yaml` |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | The project's publishable key — public by design; row-level security is what protects the data. Asked for by Render's form (§4) |
| `NEXT_PUBLIC_API_URL` | `https://<api>`. In `render.yaml` |
| `NODE_VERSION` | `22`, in `render.yaml`: what CI builds and tests with. Without it Render takes the newest release there is |

Never `NEXT_PUBLIC_DEV_AUTH`: it is a laptop's sign-in, and a production build ignores it anyway.

The three `NEXT_PUBLIC_` values are written into the pages when they are built, so changing one
means building again: **Manual Deploy** on the service's page.

It was deployed on 2026-10-06, and answered. What was run here first, the same day, is the two
commands: from a clean copy of the repository with `NODE_ENV=production`, and then the built app
held to a free instance's size, 512 MB and a tenth of a CPU. It was ready in about a second,
answered `/login` in under a tenth of one, and held 75 MB idle and 83 MB after eighty requests.

*How to tell:* `https://<web>/login` shows the sign-in card, and an address inside a workspace
leads back to it.

**On Vercel instead**, where the pilot's may go: a project on this repository with `apps/web` as
its *Root Directory*, the three `NEXT_PUBLIC_` values, and Node 22. Vercel builds `main` for
production until it is told otherwise — *Settings → Environments → Production → Branch
Tracking* — and saving that builds nothing: *Deployments → Create Deployment* does. (Its pages,
read 2026-10-06.)

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
