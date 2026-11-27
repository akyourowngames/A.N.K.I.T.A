-- Ankita anonymous usage heartbeat (opt-in only).
-- Run once in the Supabase SQL Editor of the ankita-heartbeat project.
-- Full setup: docs/heartbeat.md. The app only ever inserts rows; it never
-- reads this table, and there is no public page showing the counts.

create table if not exists public.heartbeats (
  install_id_hash text not null, -- SHA-256 of a random install UUID; the raw ID never leaves the device.
  app_version text not null,     -- e.g. '2.7.5'
  platform text not null,        -- 'win32', 'darwin' or 'linux'
  day date not null,             -- UTC calendar day of the ping
  created_at timestamptz not null default now(),
  primary key (install_id_hash, day) -- one row per install per day; a repeat ping is a no-op
);

alter table public.heartbeats enable row level security;

-- The shipped app inserts with the project's anon key (public by design).
create policy "Anyone can record a heartbeat"
  on public.heartbeats for insert to anon with check (true);

-- No select policy for anon: counts are visible only in the Supabase
-- dashboard, never from the app or any public page.
grant insert on table public.heartbeats to anon;

-- Daily active users, last 30 days (run in the SQL Editor):
-- select day, count(*) as daily_users
--   from public.heartbeats
--   where day >= current_date - interval '30 days'
--   group by day order by day desc;
--
-- Version breakdown, last 7 days:
-- select app_version, count(*) as users
--   from public.heartbeats
--   where day >= current_date - interval '7 days'
--   group by app_version order by users desc;
--
-- Platform breakdown, last 7 days:
-- select platform, count(*) as users
--   from public.heartbeats
--   where day >= current_date - interval '7 days'
--   group by platform order by users desc;
