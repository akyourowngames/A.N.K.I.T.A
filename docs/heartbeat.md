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
  no server code to deploy. `supabase/heartbeat.sql` creates it.
- Abuse surface, stated plainly: the anon key is public by design (it ships
  inside the app) and row-level security allows inserts from anyone, so a
  motivated attacker *could* inflate the count by inventing install IDs.
  The primary key `(install_id_hash, day)` caps each fake ID at one row a
  day, and the hash means fake rows are indistinguishable from real ones.
  Treat the number as directional — real enough to see growth and which
  versions people run, not auditable like a payment log. If inflation ever
  shows up, the fix is a tiny server-side check (e.g. a Vercel function
  in front of the table), not more data collection.

## Setup (Krish's clicks — the code ships inert until these are done)

The PR is deliberately inert on its own: `HEARTBEAT_ENDPOINT` and
`HEARTBEAT_ANON_KEY` in `desktop/electron/heartbeat.mjs` are empty strings,
so no ping is ever sent until the project exists and the two constants are
filled in. No new paid service; Supabase free tier covers this table.

1. **Create the project.** Open https://supabase.com/dashboard → your org
   ("Krishs Org") → **New project**. Name: `ankita-heartbeat`. Pick any
   database password (save it somewhere safe — it is not used by the app).
   Region: closest to India (Mumbai / Singapore). Wait for provisioning.
2. **Create the table.** In the new project, open **SQL Editor** → **New
   query** → paste the whole contents of `supabase/heartbeat.sql` → **Run**.
   It creates the `heartbeats` table, enables row-level security, adds the
   insert-only policy, and grants insert to `anon`.
3. **Copy the URL and anon key.** In the project, open **Project Settings**
   (gear icon, bottom left) → **API**. Copy **Project URL** (looks like
   `https://abcdefghijklm.supabase.co`) and the **`anon` `public` key**
   (a long JWT starting with `eyJ`).
4. **Wire the app.** In `desktop/electron/heartbeat.mjs`, set
   `HEARTBEAT_ENDPOINT` to the Project URL and `HEARTBEAT_ANON_KEY` to the
   anon key (the two constants at the top of the file). Commit that edit.
   The heartbeat activates in the next release; users still have to opt in.

## How Krish checks the number each morning

Supabase dashboard → project `ankita-heartbeat` → **SQL Editor** → **New
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
same rule as download counts.

## What this PR does not do

- No prompt on first launch asking to opt in. The toggle lives in Settings →
  Privacy and defaults off; users find it if they want it.
- No tracking of the terminal (`chat.mjs`) runs. The desktop app is the
  distributed artifact; terminal runs are the same installs in practice.
- No contract bump (`IPC_CONTRACT` in `desktop/shared/version.mjs`): the new
  preference field is backward-compatible both ways — an older main process
  drops the unknown key instead of failing the save, and an older renderer
  simply never shows the toggle.
