-- Weekly docs refresh (T1.12): pg_cron -> tutor.trigger_refresh() -> pg_net POST -> FastAPI
-- /tutor/internal/refresh -> incremental ingest. Local only. The URL and the shared token live in Supabase Vault
-- (written by scripts/refresh_schedule.py from .env), never in migrations or plain tables.

create extension if not exists pg_net with schema extensions;

create table if not exists tutor.refresh_run (
  id            uuid primary key default gen_random_uuid(),
  trigger       text not null check (trigger in ('cron', 'manual', 'api')),
  status        text not null default 'running' check (status in ('running', 'succeeded', 'failed')),
  started_at    timestamptz not null default now(),
  finished_at   timestamptz,
  summary       text
);
create index if not exists refresh_run_started_idx on tutor.refresh_run (started_at desc);
comment on table tutor.refresh_run is 'One row per docs refresh run (written by the backend); not visible to learners';

-- No policies and no grants for anon/authenticated: only the backend (postgres / service_role) reads it.
alter table tutor.refresh_run enable row level security;
grant all on tutor.refresh_run to service_role;

create or replace function tutor.trigger_refresh(run_trigger text default 'cron')
returns bigint
language plpgsql
security definer
set search_path = ''
as $$
declare
  target text;
  token  text;
  request_id bigint;
begin
  if run_trigger not in ('cron', 'manual') then
    raise exception 'run_trigger must be cron or manual';
  end if;
  select decrypted_secret into target from vault.decrypted_secrets where name = 'tutor_refresh_url';
  select decrypted_secret into token  from vault.decrypted_secrets where name = 'tutor_refresh_token';
  if target is null or token is null then
    raise exception 'docs refresh is not configured: run `make refresh-schedule`';
  end if;
  select net.http_post(
           url := target,
           body := jsonb_build_object('trigger', run_trigger),
           headers := jsonb_build_object('Content-Type', 'application/json', 'X-Refresh-Token', token),
           timeout_milliseconds := 10000)
    into request_id;
  return request_id;  -- the backend answers 202 at once; the ingest runs in the background
end $$;

revoke all on function tutor.trigger_refresh(text) from public, anon, authenticated, service_role;
comment on function tutor.trigger_refresh is
  'Asks the local backend to refresh the docs corpus (pg_cron job tutor-refresh-docs). URL + token from Vault.';
