"""Shared fixtures. DB-backed tests read the local stack from .env.local (`make env`) and skip if
the stack or Ollama is not reachable, so `pytest` stays usable offline."""
from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import psycopg
import pytest
from psycopg_pool import AsyncConnectionPool

ENV_LOCAL = Path(__file__).resolve().parents[2] / ".env.local"


def _local_db_url() -> str | None:
    url = os.environ.get("SUPABASE_DB_URL") or os.environ.get("DB_URL")
    if url or not ENV_LOCAL.is_file():
        return url
    for line in ENV_LOCAL.read_text().splitlines():
        if line.startswith("DB_URL="):
            return line.split("=", 1)[1].strip().strip('"')
    return None


@pytest.fixture(scope="session")
def db_url() -> str:
    url = _local_db_url()
    if not url:
        pytest.skip("local Supabase not configured (make up)")
    try:
        psycopg.connect(url, connect_timeout=2).close()
    except psycopg.OperationalError:
        pytest.skip("local Supabase not running (make up)")
    return url


@pytest.fixture(scope="session")
def ollama_up() -> None:
    base = os.environ.get("OLLAMA_URL", "http://localhost:11434")
    try:
        httpx.get(f"{base}/api/tags", timeout=2).raise_for_status()
    except httpx.HTTPError:
        pytest.skip("Ollama not reachable")


@pytest.fixture
async def pool(db_url: str) -> AsyncIterator[AsyncConnectionPool]:
    p = AsyncConnectionPool(db_url, min_size=1, max_size=2, open=False)
    await p.open()
    yield p
    await p.close()
