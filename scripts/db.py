"""Shared helpers for local-only database scripts.

Resolves the local Supabase connection from the environment (`SUPABASE_DB_URL`, or `DB_URL`
as written by `supabase status -o env`) and refuses anything that is not a local host.
"""
from __future__ import annotations

import os
import sys
from urllib.parse import urlparse, urlunparse

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "host.docker.internal"}
LAB_DB = "lab"


def admin_url() -> str:
    url = os.environ.get("SUPABASE_DB_URL") or os.environ.get("DB_URL")
    if not url:
        sys.exit("set SUPABASE_DB_URL (run `make env`, then source .env.local)")
    assert_local(url)
    return url


def lab_url() -> str:
    url = os.environ.get("LAB_DB_URL") or with_database(admin_url(), LAB_DB)
    assert_local(url)
    return url


def with_database(url: str, database: str) -> str:
    return urlunparse(urlparse(url)._replace(path=f"/{database}"))


def assert_local(url: str) -> None:
    host = urlparse(url).hostname or ""
    if host not in LOCAL_HOSTS:
        sys.exit(f"refusing non-local database host: {host!r}")
