# Anonymous usage heartbeat

One question, answered honestly: **how many people use Ankita each day?**
Today the answer is "we don't know" — Ankita has no telemetry at all. The
only automatic outbound call is the update check, which goes to GitHub
Releases and only yields total download counts (installs, not users).

The heartbeat fixes that without turning Ankita into spyware.

## What it is

- **Always opt-in, default off.** Nothing is sent unless the user turns it
  on in Settings → Privacy → "Share anonymous daily usage". There is no
  opt-out, no prompt on first launch, no dark pattern. Turning it off stops
  future pings (rows already sent can't be un-sent — see below).
- **One ping per install per day, maximum.** The app remembers the last day
  it pinged; a second launch the same day sends nothing.
- **Anonymous payload, exactly four fields:**

  | Field | Example | Why |
  |---|---|---|
  | `install_id_hash` | `9f2c…` (64 hex chars) | SHA-256 of a random UUID made once on the device. The raw ID never leaves the device, so rows can't be traced back to a machine. |
  | `app_version` | `2.7.5` | Which release people actually run. |
  | `platform` | `win32` | Windows / macOS / Linux split. |
  | `day` | `2026-11-27` | UTC calendar day. Daily actives = distinct hashes per day. |

  No prompts. No file paths. No conversation content. No IP address stored
  in the table. (Any HTTPS service's own request logs may record IPs;
  the `heartbeats` table itself holds none of that.)
- **Fails silent.** Offline, endpoint down, or a read-only profile all mean
  "no ping today" — the app works exactly as before. The ping has a 5-second
  timeout and never blocks launch or retries aggressively.

## How it works

- Client: `desktop/electron/heartbeat.mjs`. `sendHeartbeat()` does the whole
  job; `maybeSendHeartbeat()` is the fire-and-forget wrapper called from
  `desktop/electron/main.mjs` ~6 seconds after launch, next to the update
  check. State lives in `heartbeat.json` in the app's user-data folder
  (`{ installId, lastPingDay }`, mode `0600`, same as the settings file).
- Setting: `usageHeartbeat` in `desktop/electron/settings.mjs` (boolean,
  default `false`), exposed through `publicView()` and toggled in the Privacy
  tab of `desktop/renderer/src/components/SettingsDialog.tsx`.
- Endpoint: a Supabase table, written to with a plain PostgREST insert —
  no server code is needed for the app ping. `supabase/heartbeat.sql`
  creates the table and a private aggregate function for the owner dashboard.
- Owner dashboard: `admin/` is a one-page Vercel site. Its server function
  checks a private dashboard key, then calls the aggregate function with a
  server-only Supabase service key. Neither the service key nor raw install
  hashes are sent to the browser. The page shows total, daily, weekly,
  monthly, new, and returning opted-in installs, platform and version counts,
  a 30-day chart, and the 12 most recently active anonymous install aliases.
- **This is not a count of every person who uses Ankita.** It measures only
  installs that enabled the heartbeat. The short aliases in the owner view
  are still pseudonymous identifiers, not names or accounts.
- Abuse surface, stated plainly: the anon key is public by design (it ships
  inside the app) and row-level security allows inserts from anyone, so a
  motivated attacker *could* inflate the count by inventing install IDs.
  The primary key `(install_id_hash, day)` caps each fake ID at one row a
  day, and the hash means fake rows are indistinguishable from real ones.
  Treat the number as directional — real enough to see growth and which
  versions people run, not auditable like a payment log. If inflation ever
  shows up, the fix is a tiny server-side check (e.g. a Vercel function
  in front of the table), not more data collection.

## Setup

The app is wired to the existing A.N.K.I.T.A. Supabase project. Heartbeats
remain off by default; a user must turn on **Share anonymous daily usage**
in Settings → Privacy before any ping is sent. No new paid service is needed.

**Current setup:** the heartbeat table, insert-only anon policy, and owner
aggregate are applied in `A.N.K.I.T.A` under `akyourowngames`. A live opt-in
test insert succeeded and its temporary row was removed. The owner page is
deployed at [ankita-owner-dashboard.vercel.app](https://ankita-owner-dashboard.vercel.app)
with its Supabase secret and owner key stored as encrypted Vercel production
settings. Its protected API returned the live zero-user metrics. This work
does not publish a new desktop release, so existing installs do not send
heartbeats until a future release includes the wired endpoint.

1. **Create the database objects.** Run the whole contents of
   `supabase/heartbeat.sql` in the A.N.K.I.T.A. project’s SQL Editor. It
   enables row-level security, permits anonymous inserts only, and adds an
   aggregate function callable only by the Supabase service role.
2. **Set up the owner page.** Deploy `admin/` as its own Vercel project.
   Add `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, and a long random
   `ADMIN_ACCESS_TOKEN` as server-side environment variables. A Supabase
   secret key maps to the service role; never send it to a browser or desktop
   app. Open the deployed page and enter the dashboard token when prompted.
3. The desktop app’s publishable Supabase key is safe to ship because users
   can only insert an anonymous daily row. Existing installs receive this
   wiring after a future desktop release; this PR creates no release.

## How the owner checks the numbers

The Vercel owner page shows the headline totals and recent anonymous installs.
For a direct database check, open the project’s SQL Editor and use:

Supabase dashboard → project `A.N.K.I.T.A` → **SQL Editor** → **New
query** → paste → **Run**:

```sql
-- Daily active users, last 30 days
select day, count(*) as daily_users
  from public.heartbeats
  where day >= current_date - interval '30 days'
  group by day order by day desc;
```

```sql
-- Version breakdown, last 7 days
select app_version, count(*) as users
  from public.heartbeats
  where day >= current_date - interval '7 days'
  group by app_version order by users desc;
```

These numbers are **internal only** — never published, never cited outward,
same rule as download counts. The count is directional because public client
inserts can be faked; it is not an audited list of people.

## What this PR does not do

- No prompt on first launch asking to opt in. The toggle lives in Settings →
  Privacy and defaults off; users find it if they want it.
- No tracking of the terminal (`chat.mjs`) runs. The desktop app is the
  distributed artifact; terminal runs are the same installs in practice.
- No contract bump (`IPC_CONTRACT` in `desktop/shared/version.mjs`): the new
  preference field is backward-compatible both ways — an older main process
  drops the unknown key instead of failing the save, and an older renderer
  simply never shows the toggle.
