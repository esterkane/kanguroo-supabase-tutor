#!/usr/bin/env python3
"""Manage broken labs in the disposable `lab` database.

Commands:
  list                 show available labs
  install <slug>       run labs/<slug>/setup.sql in the lab DB (resets the lab schema)
  reset <slug>         same as install: drop the lab schema and re-run setup.sql
  check <slug>         run labs/<slug>/checks.sql (pgTAP); exit 1 unless every test passes
  solve <slug>         apply labs/<slug>/solution.sql (for tests / exam review only)
  sync                 regenerate supabase/seed.sql (tutor.lab registry) from labs/*/lab.yaml

Local only: targets LAB_DB_URL, or SUPABASE_DB_URL with the database switched to `lab`.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import psycopg
import seed
import yaml
from db import lab_url

LABS = Path(__file__).resolve().parents[1] / "labs"


def lab_dir(slug: str) -> Path:
    path = LABS / slug
    if not (path / "lab.yaml").is_file():
        sys.exit(f"unknown lab {slug!r}; try `lab.py list`")
    return path


def schema_of(slug: str) -> str:
    # 01-rls-vs-grant -> lab01 (the schema setup.sql creates)
    return "lab" + slug.split("-", 1)[0]


def run_script(sql: str) -> list[str]:
    """Run a multi-statement script; return every text value from every result set (TAP lines)."""
    lines: list[str] = []
    with psycopg.connect(lab_url(), autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(sql.encode())  # bytes → simple query protocol, multiple statements allowed
        while True:
            if cur.description:
                for row in cur.fetchall():
                    lines += [str(v) for v in row if isinstance(v, str)]
            if not cur.nextset():
                break
    return lines


def cmd_list() -> None:
    for path in sorted(LABS.glob("*/lab.yaml")):
        spec = yaml.safe_load(path.read_text())
        print(f"{spec['slug']:<24} phase {spec['phase']}  {spec.get('difficulty', ''):<6}  {spec['title']}")


DATASET_HINT = {"olist": "make olist (download kaggle.com/datasets/olistbr/brazilian-ecommerce into data/olist/ first)"}


def missing_requirements(slug: str) -> list[str]:
    """Datasets (schemas in the lab DB) a lab reads from but that are not imported yet."""
    required = yaml.safe_load((lab_dir(slug) / "lab.yaml").read_text()).get("requires", [])
    with psycopg.connect(lab_url()) as conn:
        return [r for r in required if not (conn.execute("select to_regnamespace(%s)", (r,)).fetchone() or [None])[0]]


def cmd_install(slug: str) -> None:
    if missing := missing_requirements(slug):
        print(f"skip {slug}: needs dataset(s) {missing}; run " + "; ".join(DATASET_HINT.get(m, m) for m in missing))
        sys.exit(3)
    path = lab_dir(slug)
    run_script(f"drop schema if exists {schema_of(slug)} cascade;\n" + (path / "setup.sql").read_text())
    print(f"installed {slug}")


def run_statements(sql: str) -> None:
    """Run statement by statement and keep going past errors, like `psql` without ON_ERROR_STOP.

    solution.sql files show the failing "before" query on purpose; the fix comes after it.
    Splits on a `;` that ends a line, so lab files keep one statement terminator per line end.
    """
    stmts = [s.strip() for s in re.split(r";[ \t]*(?:--[^\n]*)?\n", sql + "\n")]
    with psycopg.connect(lab_url(), autocommit=True) as conn:
        for stmt in stmts:
            if not re.sub(r"--[^\n]*", "", stmt).strip():
                continue
            try:
                conn.execute(stmt.encode())
            except psycopg.Error as e:
                print(f"  (expected?) {e.sqlstate}: {str(e).splitlines()[0]}")


def cmd_check(slug: str) -> int:
    try:
        lines = run_script((lab_dir(slug) / "checks.sql").read_text())
    except psycopg.Error as e:
        print(f"{e.sqlstate}: {str(e).splitlines()[0]}\nFAIL")
        return 1
    for line in lines:
        print(line)
    tap = [ln for ln in lines if re.match(r"^(not )?ok \d+", ln)]
    plan = next((ln for ln in lines if re.match(r"^1\.\.\d+$", ln)), None)
    planned = int(plan.split("..")[1]) if plan else -1
    passed = all(ln.startswith("ok") for ln in tap) and len(tap) == planned
    print("PASS" if passed else "FAIL")
    return 0 if passed else 1


def cmd_solve(slug: str) -> None:
    run_statements((lab_dir(slug) / "solution.sql").read_text())
    print(f"applied solution for {slug}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["list", "install", "reset", "check", "solve", "sync"])
    ap.add_argument("slug", nargs="?")
    args = ap.parse_args()

    if args.command in {"install", "reset", "check", "solve"} and not args.slug:
        ap.error(f"{args.command} needs a lab slug")
    if args.command == "list":
        cmd_list()
    elif args.command in {"install", "reset"}:
        cmd_install(args.slug)
    elif args.command == "check":
        sys.exit(cmd_check(args.slug))
    elif args.command == "solve":
        cmd_solve(args.slug)
    elif args.command == "sync":
        seed.SEED.write_text(seed.render())
        print("wrote supabase/seed.sql")


if __name__ == "__main__":
    main()
