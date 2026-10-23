#!/usr/bin/env python3
"""Weekly docs refresh schedule (T1.12), local only.

  install   store the refresh URL + TUTOR_REFRESH_TOKEN (from .env) in Supabase Vault and schedule the pg_cron
            job `tutor-refresh-docs` (default: Mondays 03:00 UTC) that calls tutor.trigger_refresh()
  status    show the job, its last cron runs and the last refresh runs (the token is never printed)
  run-now   trigger a refresh through the same pg_net path the cron job uses
  remove    unschedule the job (Vault secrets stay; `install` overwrites them)

The backend must be running for a refresh to happen (`make dev` or the kaenguru-api preview): pg_net posts to
http://host.docker.internal:<API_PORT>/tutor/internal/refresh, which Docker Desktop forwards to this Mac.

Usage:
  uv run python scripts/refresh_schedule.py install [--cron "0 3 * * 1"] [--url URL]
  uv run python scripts/refresh_schedule.py status
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import psycopg
from db import admin_url

JOB = "tutor-refresh-docs"
DEFAULT_CRON = "0 3 * * 1"
SECRET_DESCRIPTION = "Kaenguru tutor docs refresh (scripts/refresh_schedule.py)"


def upsert_secret(conn: psycopg.Connection, name: str, value: str) -> None:
    row = conn.execute("select id from vault.secrets where name = %s", (name,)).fetchone()
    if row:
        conn.execute("select vault.update_secret(%s, %s)", (row[0], value))
    else:
        conn.execute("select vault.create_secret(%s, %s, %s)", (value, name, SECRET_DESCRIPTION))


def install(conn: psycopg.Connection, cron: str, url: str) -> None:
    token = os.environ.get("TUTOR_REFRESH_TOKEN", "")
    if token in ("", "change-me"):
        sys.exit("set a real TUTOR_REFRESH_TOKEN in .env first (the backend checks the same value)")
    upsert_secret(conn, "tutor_refresh_url", url)
    upsert_secret(conn, "tutor_refresh_token", token)
    job = conn.execute("select cron.schedule(%s, %s, %s)", (JOB, cron, "select tutor.trigger_refresh('cron')")).fetchone()
    print(f"scheduled {JOB} (job {job[0] if job else '?'}) at '{cron}' -> {url}")


def status(conn: psycopg.Connection) -> None:
    job = conn.execute("select jobid, schedule, command, active from cron.job where jobname = %s", (JOB,)).fetchone()
    print(f"job: {job if job else 'not scheduled (make refresh-schedule)'}")
    secrets = [r[0] for r in conn.execute(
        "select name from vault.secrets where name in ('tutor_refresh_url', 'tutor_refresh_token') order by name")]
    print(f"vault secrets present: {secrets or 'none'}")
    if job:
        for r in conn.execute("select status, start_time, return_message from cron.job_run_details where jobid = %s "
                              "order by start_time desc limit 3", (job[0],)):
            print(f"  cron run: {r[0]:<10} {r[1]:%Y-%m-%d %H:%M} {(r[2] or '')[:80]}")
    for r in conn.execute("select trigger, status, started_at, finished_at, summary from tutor.refresh_run "
                          "order by started_at desc limit 5"):
        took = f"{(r[3] - r[2]).total_seconds():.0f}s" if r[3] else "running"
        print(f"  refresh: {r[0]:<7} {r[1]:<10} {r[2]:%Y-%m-%d %H:%M} {took:>8}  {(r[4] or '')[:110]}")


def run_now(conn: psycopg.Connection) -> None:
    row = conn.execute("select tutor.trigger_refresh('manual')").fetchone()
    request_id = row[0] if row else None
    for _ in range(60):  # pg_net sends asynchronously; wait for the backend's answer
        resp = conn.execute("select status_code, content::text, error_msg from net._http_response where id = %s",
                            (request_id,)).fetchone()
        if resp:
            print(f"backend answered {resp[0]}: {(resp[1] or resp[2] or '')[:200]}")
            return
        time.sleep(0.25)
    print("no answer from the backend yet (is it running?)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["install", "status", "run-now", "remove"])
    ap.add_argument("--cron", default=DEFAULT_CRON, help="cron expression in UTC (default: Mondays 03:00)")
    ap.add_argument("--url", default=f"http://host.docker.internal:{os.environ.get('API_PORT', '8020')}"
                                     "/tutor/internal/refresh", help="refresh endpoint as seen from the DB container")
    a = ap.parse_args()
    with psycopg.connect(admin_url(), autocommit=True) as conn:
        if a.command == "install":
            install(conn, a.cron, a.url)
        elif a.command == "status":
            status(conn)
        elif a.command == "run-now":
            run_now(conn)
        else:
            gone = conn.execute("select cron.unschedule(%s) where exists (select 1 from cron.job where jobname = %s)",
                                (JOB, JOB)).fetchone()
            print(f"unscheduled {JOB}" if gone else f"{JOB} was not scheduled")


if __name__ == "__main__":
    main()
