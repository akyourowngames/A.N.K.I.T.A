-- Ankita required pseudonymous daily installation usage heartbeat.
-- Run once in the Supabase SQL Editor of the A.N.K.I.T.A project.
-- Full setup: docs/heartbeat.md. The app only ever inserts rows; it never
-- reads this table, and there is no public page showing the counts.

create table if not exists public.heartbeats (
  install_id_hash text not null, -- SHA-256 of a random install UUID; the raw ID never leaves the device.
  app_version text not null,     -- e.g. '2.7.6'
  platform text not null,        -- 'win32', 'darwin' or 'linux'
  day date not null,             -- UTC calendar day of the ping
  created_at timestamptz not null default now(),
  primary key (install_id_hash, day) -- one row per install per day; a repeat ping is a no-op
);

alter table public.heartbeats enable row level security;

-- The shipped app inserts with the project's anon key (public by design).
drop policy if exists "Anyone can record a heartbeat" on public.heartbeats;
create policy "Anyone can record a heartbeat"
  on public.heartbeats for insert to anon with check (true);

-- No select policy for anon: counts are visible only in the Supabase
-- dashboard, never from the app or any public page.
revoke all on table public.heartbeats from public, anon, authenticated;
grant insert on table public.heartbeats to anon;
grant select on table public.heartbeats to service_role;

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

-- Owner-only aggregate endpoint for the Vercel dashboard. The client keeps
-- the service-role key server-side; anon and authenticated cannot execute it.
create or replace function public.heartbeat_admin_metrics()
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
  with utc_today as (
    select timezone('UTC', now())::date as day
  ),
  install_dates as (
    select install_id_hash, min(day) as first_seen, max(day) as last_seen
      from public.heartbeats
     group by install_id_hash
  ),
  latest_install_rows as (
    select distinct on (install_id_hash)
           install_id_hash, app_version, platform, day
      from public.heartbeats
     order by install_id_hash, day desc, created_at desc
  ),
  daily_series as (
    select generated.day::date as day
      from utc_today
      cross join generate_series(
        (utc_today.day - 29)::timestamp,
        utc_today.day::timestamp,
        interval '1 day'
      ) as generated(day)
  ),
  daily_counts as (
    select daily_series.day, count(distinct heartbeats.install_id_hash) as users
      from daily_series
      left join public.heartbeats on heartbeats.day = daily_series.day
     group by daily_series.day
  )
  select jsonb_build_object(
    'updatedAt', now(),
    'summary', jsonb_build_object(
      'totalUsers', (select count(*) from install_dates),
      'activeToday', (
        select count(distinct heartbeats.install_id_hash)
          from public.heartbeats, utc_today
         where heartbeats.day = utc_today.day
      ),
      'active7Days', (
        select count(distinct heartbeats.install_id_hash)
          from public.heartbeats, utc_today
         where heartbeats.day between utc_today.day - 6 and utc_today.day
      ),
      'active30Days', (
        select count(distinct heartbeats.install_id_hash)
          from public.heartbeats, utc_today
         where heartbeats.day between utc_today.day - 29 and utc_today.day
      ),
      'newUsers30Days', (
        select count(*) from install_dates, utc_today
         where first_seen between utc_today.day - 29 and utc_today.day
      ),
      'returningUsers30Days', (
        select count(*) from install_dates, utc_today
         where last_seen between utc_today.day - 29 and utc_today.day
           and first_seen < utc_today.day - 29
      )
    ),
    'daily', coalesce((
      select jsonb_agg(jsonb_build_object('day', day, 'users', users) order by day)
        from daily_counts
    ), '[]'::jsonb),
    'platforms', coalesce((
      select jsonb_agg(jsonb_build_object('name', platform, 'users', users) order by users desc)
        from (
          select platform, count(*) as users
            from latest_install_rows, utc_today
           where latest_install_rows.day between utc_today.day - 29 and utc_today.day
           group by platform
        ) as platform_counts
    ), '[]'::jsonb),
    'versions', coalesce((
      select jsonb_agg(jsonb_build_object('name', app_version, 'users', users) order by users desc)
        from (
          select app_version, count(*) as users
            from latest_install_rows, utc_today
           where latest_install_rows.day between utc_today.day - 29 and utc_today.day
           group by app_version
        ) as version_counts
    ), '[]'::jsonb),
    'recentUsers', coalesce((
      select jsonb_agg(
        jsonb_build_object(
          'id', recent.install_id,
          'firstSeen', recent.first_seen,
          'lastSeen', recent.last_seen,
          'platform', recent.platform,
          'version', recent.app_version
        ) order by recent.last_seen desc
      )
        from (
          select left(latest_install_rows.install_id_hash, 10) as install_id,
                 install_dates.first_seen, install_dates.last_seen,
                 latest_install_rows.platform, latest_install_rows.app_version
            from install_dates
            join latest_install_rows using (install_id_hash)
            cross join utc_today
           where install_dates.last_seen between utc_today.day - 29 and utc_today.day
           order by install_dates.last_seen desc
           limit 12
        ) as recent
    ), '[]'::jsonb)
  );
$$;

revoke all on function public.heartbeat_admin_metrics() from public, anon, authenticated;
grant execute on function public.heartbeat_admin_metrics() to service_role;
