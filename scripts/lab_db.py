#!/usr/bin/env python3
"""Create the disposable `lab` database on the local Supabase stack.

Supabase-equivalent roles (cluster-wide, normally already present on the CLI stack) plus an
auth.uid()/auth.role()/auth.jwt() shim that reads `request.jwt.claims` like a Supabase project.
Idempotent. Local only.

Usage:
  uv run python scripts/lab_db.py           # create / update
  uv run python scripts/lab_db.py --drop    # drop the lab database
"""
from __future__ import annotations

import argparse

import psycopg
from db import LAB_DB, admin_url, lab_url

ROLES_SQL = """
do $$ begin
  if not exists (select 1 from pg_roles where rolname='anon') then create role anon nologin noinherit; end if;
  if not exists (select 1 from pg_roles where rolname='authenticated') then
    create role authenticated nologin noinherit;
  end if;
  if not exists (select 1 from pg_roles where rolname='service_role') then
    create role service_role nologin noinherit bypassrls;
  end if;
end $$;
"""

# nullif(..., '') matters: after a transaction-local set_config the setting reverts to '' (not NULL).
SHIM_SQL = """
create extension if not exists pgtap;

create schema if not exists auth;
grant usage on schema auth to anon, authenticated, service_role;

create or replace function auth.jwt() returns jsonb
language sql stable set search_path = '' as $$
  select coalesce(nullif(current_setting('request.jwt.claim', true), ''),
                  nullif(current_setting('request.jwt.claims', true), ''))::jsonb
$$;
create or replace function auth.uid() returns uuid
language sql stable set search_path = '' as $$
  select nullif(coalesce(nullif(current_setting('request.jwt.claim.sub', true), ''),
                         nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub'), '')::uuid
$$;
create or replace function auth.role() returns text
language sql stable set search_path = '' as $$
  select nullif(coalesce(nullif(current_setting('request.jwt.claim.role', true), ''),
                         nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'role'), '')::text
$$;
grant execute on function auth.jwt(), auth.uid(), auth.role() to anon, authenticated, service_role;
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--drop", action="store_true", help="drop the lab database and exit")
    args = ap.parse_args()

    with psycopg.connect(admin_url(), autocommit=True) as conn:
        if args.drop:
            conn.execute(f"drop database if exists {LAB_DB} with (force)")
            print("dropped lab")
            return
        if not conn.execute("select 1 from pg_database where datname = %s", (LAB_DB,)).fetchone():
            conn.execute(f"create database {LAB_DB}")
        conn.execute(ROLES_SQL)
        conn.execute("grant anon, authenticated, service_role to current_user")

    with psycopg.connect(lab_url(), autocommit=True) as conn:
        conn.execute(SHIM_SQL)
    print("lab database ready")


if __name__ == "__main__":
    main()
