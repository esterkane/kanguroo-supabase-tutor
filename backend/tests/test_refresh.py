"""Docs refresh (T1.12): RefreshManager runs and the /internal/refresh endpoints, with stand-in commands."""
from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator
from typing import Any

import httpx
import psycopg
import pytest
from fastapi import FastAPI
from psycopg_pool import AsyncConnectionPool

from backend.tutor.refresh import RefreshManager
from backend.tutor.router import router

TOKEN = "test-refresh-token-0123456789"
OK = [sys.executable, "-c", "print('stage'); print('831 sources, 0 chunks written, 0 index failures')"]
FAIL = [sys.executable, "-c", "import sys; print('cannot fetch index'); sys.exit(2)"]
SLOW = [sys.executable, "-c", "import time; time.sleep(2); print('done')"]


@pytest.fixture
async def refresh_pool(db_url: str) -> AsyncIterator[AsyncConnectionPool]:
    with psycopg.connect(db_url) as conn:  # before opening the pool: a failure here must not leak it
        row = conn.execute("select clock_timestamp()").fetchone()
        assert row is not None
        before = row[0]
    pool = AsyncConnectionPool(db_url, min_size=1, max_size=2, open=False)
    await pool.open()
    try:
        yield pool
    finally:
        await pool.close()
        with psycopg.connect(db_url, autocommit=True) as conn:  # only the rows these tests created
            conn.execute("delete from tutor.refresh_run where started_at >= %s", (before,))


async def finished(manager: RefreshManager) -> dict[str, Any]:
    assert manager.task is not None
    await manager.task
    return (await manager.recent(1))[0]


def test_token_handling() -> None:
    assert not RefreshManager(None, "", None).configured  # type: ignore[arg-type]
    assert not RefreshManager(None, "", "change-me").token_ok("change-me")  # type: ignore[arg-type]
    m = RefreshManager(None, "", TOKEN)  # type: ignore[arg-type]
    assert m.token_ok(TOKEN) and not m.token_ok(TOKEN[:-1]) and not m.token_ok(None)


async def test_successful_and_failed_runs_are_recorded(refresh_pool: AsyncConnectionPool, db_url: str) -> None:
    ok = RefreshManager(refresh_pool, db_url, TOKEN, command=OK)
    run_id, started = await ok.start("manual")
    assert started
    row = await finished(ok)
    assert row["id"] == run_id and row["status"] == "succeeded" and row["trigger"] == "manual"
    assert row["summary"] == "831 sources, 0 chunks written, 0 index failures" and row["finished_at"]

    bad = RefreshManager(refresh_pool, db_url, TOKEN, command=FAIL)
    await bad.start("cron")
    row = await finished(bad)
    assert row["status"] == "failed" and row["summary"] == "cannot fetch index"


async def test_only_one_run_at_a_time(refresh_pool: AsyncConnectionPool, db_url: str) -> None:
    m = RefreshManager(refresh_pool, db_url, TOKEN, command=SLOW)
    first, started = await m.start("cron")
    second, started_again = await m.start("manual")
    assert started and not started_again and second == first
    assert (await finished(m))["status"] == "succeeded"


async def test_endpoints(refresh_pool: AsyncConnectionPool, db_url: str) -> None:
    app = FastAPI()
    app.include_router(router, prefix="/tutor")
    app.state.tutor = type("Svc", (), {"refresh": RefreshManager(refresh_pool, db_url, TOKEN, command=SLOW)})()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.post("/tutor/internal/refresh")).status_code == 401
        assert (await client.post("/tutor/internal/refresh", headers={"X-Refresh-Token": "nope"})).status_code == 401
        res = await client.post("/tutor/internal/refresh", json={"trigger": "cron"}, headers={"X-Refresh-Token": TOKEN})
        assert res.status_code == 202 and res.json()["started"] is True
        again = await client.post("/tutor/internal/refresh", headers={"X-Refresh-Token": TOKEN})
        assert again.status_code == 409
        status = (await client.get("/tutor/internal/refresh", headers={"X-Refresh-Token": TOKEN})).json()
        assert status["running"] is True and status["runs"][0]["trigger"] == "cron"
        await app.state.tutor.refresh.task
        app.state.tutor.refresh.token = "change-me"
        assert (await client.post("/tutor/internal/refresh", headers={"X-Refresh-Token": "change-me"})).status_code == 503
    await asyncio.sleep(0)
