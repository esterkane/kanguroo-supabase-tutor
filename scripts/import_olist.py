#!/usr/bin/env python3
"""Import the Olist e-commerce dataset into the disposable `lab` database.

Stage 1: every CSV in data/olist/ → schema olist_staging, all columns text (messy rows accepted).
Stage 2: datasets/olist/transform.sql → schema olist, typed, with keys and synthetic app_users.
Idempotent: both schemas are dropped and rebuilt (labs that read from olist are reinstalled with
`scripts/lab.py install <slug>` afterwards). No psql needed: COPY ... FROM STDIN via psycopg.

Get the data first (Kaggle, ~45 MB zip): kaggle.com/datasets/olistbr/brazilian-ecommerce → unzip into data/olist/.

Usage:
  uv run python scripts/import_olist.py           # import / re-import
  uv run python scripts/import_olist.py --check   # only report row counts
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

import psycopg
from db import lab_url

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "olist"
TRANSFORM = ROOT / "datasets" / "olist" / "transform.sql"
FILES = {  # staging table → CSV file
    "customers": "olist_customers_dataset.csv",
    "geolocation": "olist_geolocation_dataset.csv",
    "order_items": "olist_order_items_dataset.csv",
    "order_payments": "olist_order_payments_dataset.csv",
    "order_reviews": "olist_order_reviews_dataset.csv",
    "orders": "olist_orders_dataset.csv",
    "products": "olist_products_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
    "category_translation": "product_category_name_translation.csv",
}
TABLES = ["customers", "orders", "order_items", "order_payments", "order_reviews", "products", "sellers",
          "geolocation", "category_translation", "app_users"]


def header(path: Path) -> list[str]:
    first = path.open(encoding="utf-8-sig").readline()  # one file starts with a byte-order mark
    return [re.sub(r"[^a-z0-9_]", "_", col.strip().strip('"').lower()) for col in first.split(",")]


def stage(conn: psycopg.Connection) -> None:
    conn.execute("drop schema if exists olist_staging cascade")
    conn.execute("create schema olist_staging")
    for table, name in FILES.items():
        path = DATA / name
        cols = ", ".join(f"{c} text" for c in header(path))
        conn.execute(f"create table olist_staging.{table} ({cols})".encode())
        started = time.monotonic()
        with conn.cursor().copy(f"copy olist_staging.{table} from stdin (format csv, header true)".encode()) as cp, \
                path.open("rb") as fh:
            while chunk := fh.read(1 << 20):
                cp.write(chunk)
        print(f"  staged {table:<22} {time.monotonic() - started:5.1f}s")


def counts(conn: psycopg.Connection) -> list[tuple[str, int | None, int | None]]:
    rows = []
    for table in TABLES:
        out = []
        for schema in ("olist_staging", "olist"):
            exists = conn.execute("select to_regclass(%s)", (f"{schema}.{table}",)).fetchone()
            if exists and exists[0]:
                n = conn.execute(f"select count(*) from {schema}.{table}".encode()).fetchone()
                out.append(n[0] if n else None)
            else:
                out.append(None)
        rows.append((table, out[0], out[1]))
    return rows


def report(conn: psycopg.Connection) -> None:
    print(f"\n  {'table':<22} {'staging':>10} {'typed':>10}")
    for table, staged, typed in counts(conn):
        print(f"  {table:<22} {staged if staged is not None else '-':>10} {typed if typed is not None else '-':>10}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="only print row counts")
    args = ap.parse_args()

    with psycopg.connect(lab_url(), autocommit=True) as conn:
        if args.check:
            report(conn)
            return
        missing = [n for n in FILES.values() if not (DATA / n).is_file()]
        if missing:
            sys.exit(f"missing in {DATA.relative_to(ROOT)}: {', '.join(missing)}\n"
                     "download kaggle.com/datasets/olistbr/brazilian-ecommerce and unzip it there")
        print("stage 1: CSV → olist_staging")
        stage(conn)
        print("stage 2: transform → olist (typed, keys, synthetic app_users)")
        started = time.monotonic()
        conn.execute(TRANSFORM.read_text(encoding="utf-8").encode())
        print(f"  transformed in {time.monotonic() - started:.1f}s")
        report(conn)
        print("\nolist ready in the lab database. Reinstall labs that use it, e.g. scripts/lab.py install 04-missing-index")


if __name__ == "__main__":
    main()
