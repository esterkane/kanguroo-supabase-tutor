---
name: supabase-local-lab
description: Start, reset and inspect the local Supabase CLI stack and the disposable `lab` database used by the tutor. Use for Makefile targets, config.toml, roles, extensions, `supabase status`, smoke tests.
---

# Local Supabase lab stack

## Principles
- Never assume ports or keys. Always read them: `npx supabase status -o env` → export into
  the environment the backend reads (`SUPABASE_URL`, `SUPABASE_ANON_KEY`,
  `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_DB_URL`).
- Local only. Refuse any command that contains `--linked`, `--project-ref`, or a
  `*.supabase.co` host unless Saru explicitly asked for a hosted lesson in this session.
- Verify CLI syntax against the corpus (`llms/cli.txt`) before writing it into docs or
  Makefile — CLI flags change between releases.

## Stack setup
1. `npx supabase init` (once). In `supabase/config.toml` set `[db] major_version = 17`
   and keep `[db.pooler] enabled = true` (so Supavisor lessons work locally).
2. Extensions are enabled per database by migration, not config: `create extension if
   not exists vector; create extension if not exists pg_cron; create extension if not
   exists pgtap;` (see core migration). If the CLI image lacks one, record it in
   `docs/DECISIONS.md` rather than working around it silently.
3. `npx supabase start` → `npx supabase status`. Studio is at the URL shown — never hardcode.

## Lab database
`scripts/lab_db.sh` connects with `SUPABASE_DB_URL` (postgres superuser) and runs:
```sql
create database lab;
```
then connects to `lab` and creates the Supabase-equivalent roles if missing
(`anon`, `authenticated`, `service_role`, `authenticator` with `noinherit`), grants
`usage on schema public`, and installs a minimal `auth` schema with
`auth.uid()`, `auth.role()`, `auth.jwt()` reading `request.jwt.claims` exactly like a
Supabase project does, so RLS examples behave identically. Idempotent (`if not exists`,
`do $$ ... $$` guards).

Each lab lives in its own schema; `scripts/lab.py reset <slug>` does
`drop schema if exists <slug> cascade` then re-runs `labs/<slug>/setup.sql`.

## Simulating a request as a role (for the lab runner and for lessons)
```sql
begin;
  set local role authenticated;
  select set_config('request.jwt.claims',
    '{"sub":"11111111-1111-1111-1111-111111111111","role":"authenticated"}', true);
  -- statement under test
rollback;
```
Teach that `set local role` + `request.jwt.claims` is what PostgREST does per request.

## Makefile contract
- `make up` → start stack, export env, create lab DB, apply migrations (`db reset` only
  when `RESET=1`), install default labs.
- `make smoke` → stack reachable, `select count(*) from tutor.docs_chunk` ≥ 0,
  `tutor.hybrid_search` returns without error, lab DB has role `authenticated`.
- `make down` → `npx supabase stop` (keep volumes unless `PURGE=1`).

## Useful inspection commands to teach early
```
npx supabase inspect db long-running-queries --local
npx supabase inspect db locks --local
npx supabase inspect db blocking --local
npx supabase inspect db outliers --local
npx supabase inspect db vacuum-stats --local
npx supabase inspect db bloat --local
npx supabase inspect db replication-slots --local
npx supabase db lint --local
npx supabase test db
```
