#!/usr/bin/env python3
"""Smoke test the local stack: schema present, topics seeded, hybrid_search callable,
lab DB has the Supabase roles and the auth shim, lab 01 installed and still broken.

Usage:
  uv run python scripts/smoke.py
"""
from __future__ import annotations

import argparse
import sys

import psycopg
from db import admin_url, lab_url

ZERO = "array_fill(0, array[768])::extensions.vector(768)"


def main() -> None:
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    failures = 0

    def check(label: str, ok: bool, detail: object = "") -> None:
        nonlocal failures
        failures += not ok
        print(f"{'ok  ' if ok else 'FAIL'}  {label}  {detail}")

    with psycopg.connect(admin_url()) as conn:
        chunks = conn.execute("select count(*) from tutor.docs_chunk").fetchone()
        check("tutor.docs_chunk readable", chunks is not None, f"{chunks[0] if chunks else '?'} chunks")
        topics = conn.execute("select count(*) from tutor.topic").fetchone()
        check("tutor.topic seeded", bool(topics and topics[0] > 0), f"{topics[0] if topics else 0} topics")
        labs = conn.execute("select count(*) from tutor.lab").fetchone()
        check("tutor.lab registered", bool(labs and labs[0] > 0), f"{labs[0] if labs else 0} labs")
        hits = conn.execute(f"select count(*) from tutor.hybrid_search('row level security', {ZERO}, 3)").fetchone()
        n_hits = hits[0] if hits else 0
        if chunks and chunks[0] > 0:
            check("tutor.hybrid_search returns rows", n_hits > 0, f"{n_hits} hits for 'row level security'")
        else:
            check("tutor.hybrid_search callable (empty corpus: make ingest)", True)

    with psycopg.connect(lab_url()) as conn:
        roles = {r[0] for r in conn.execute(
            "select rolname from pg_roles where rolname in ('anon','authenticated','service_role')")}
        check("lab roles exist", len(roles) == 3, sorted(roles))
        conn.execute("set local role authenticated")
        conn.execute("""select set_config('request.jwt.claims',
                        '{"sub":"11111111-1111-1111-1111-111111111111","role":"authenticated"}', true)""")
        uid = conn.execute("select auth.uid()::text").fetchone()
        check("auth.uid() shim reads claims", bool(uid and uid[0].startswith("1111")), uid[0] if uid else None)
        conn.rollback()
        try:
            with conn.transaction():
                conn.execute("set local role authenticated")
                conn.execute("select * from lab01.orders")
            check("lab01 reproduces 42501", False, "select succeeded - lab already solved?")
        except psycopg.errors.InsufficientPrivilege:
            check("lab01 reproduces 42501", True)
        except psycopg.errors.UndefinedTable:
            check("lab01 reproduces 42501", False, "lab01 not installed")

    print("smoke ok" if failures == 0 else f"smoke FAILED ({failures})")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
