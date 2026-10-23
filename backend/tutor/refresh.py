"""Docs refresh runs (T1.12): started by pg_cron via pg_net (or by hand), executed as a background subprocess.

The ingest is incremental (unchanged pages are skipped by content hash), so a weekly run mostly downloads and
compares. One run at a time; each run is recorded in tutor.refresh_run with its summary line.
"""
from __future__ import annotations

import asyncio
import hmac
import os
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

ROOT = Path(__file__).resolve().parents[2]
INGEST = [sys.executable, str(ROOT / "scripts" / "ingest_llms.py")]
RUN_TIMEOUT_S = 30 * 60
PLACEHOLDER_TOKENS = {"", "change-me"}


class RefreshManager:
    def __init__(self, pool: AsyncConnectionPool, db_url: str, token: str | None,
                 command: list[str] | None = None) -> None:
        self.pool = pool
        self.db_url = db_url
        self.token = token or ""
        self.command = command or INGEST
        self.task: asyncio.Task[None] | None = None
        self.run_id: UUID | None = None

    @property
    def configured(self) -> bool:
        return self.token not in PLACEHOLDER_TOKENS

    def token_ok(self, given: str | None) -> bool:
        return self.configured and hmac.compare_digest(self.token.encode(), (given or "").encode())

    @property
    def running(self) -> bool:
        return self.task is not None and not self.task.done()

    async def start(self, trigger: str) -> tuple[UUID, bool]:
        """(run id, started). When a run is already going, returns its id and False."""
        if self.running and self.run_id:
            return self.run_id, False
        async with self.pool.connection() as conn:
            cur = await conn.execute("insert into tutor.refresh_run (trigger) values (%s) returning id", (trigger,))
            row = await cur.fetchone()
            assert row is not None
        self.run_id = row[0]
        self.task = asyncio.create_task(self._run(row[0]))
        return row[0], True

    async def _run(self, run_id: UUID) -> None:
        env = {**os.environ, "SUPABASE_DB_URL": self.db_url}
        status, summary = "failed", ""
        try:
            proc = await asyncio.create_subprocess_exec(*self.command, cwd=ROOT, env=env,
                                                        stdout=asyncio.subprocess.PIPE,
                                                        stderr=asyncio.subprocess.STDOUT)
            try:
                out, _ = await asyncio.wait_for(proc.communicate(), RUN_TIMEOUT_S)
            except TimeoutError:
                proc.kill()
                out, summary = b"", f"timed out after {RUN_TIMEOUT_S}s"
            lines = [ln for ln in out.decode(errors="replace").splitlines() if ln.strip()]
            summary = summary or (lines[-1] if lines else "")
            status = "succeeded" if proc.returncode == 0 else "failed"
        except Exception as e:  # noqa: BLE001 - a failed run is recorded, never raised into the event loop
            summary = f"{type(e).__name__}: {e}"
        finally:
            async with self.pool.connection() as conn:
                await conn.execute("update tutor.refresh_run set status = %s, summary = %s, finished_at = now() "
                                   "where id = %s", (status, summary[:2000], run_id))

    async def recent(self, limit: int = 5) -> list[dict[str, Any]]:
        async with self.pool.connection() as conn:
            cur = conn.cursor(row_factory=dict_row)
            await cur.execute("select id, trigger, status, started_at, finished_at, summary from tutor.refresh_run "
                              "order by started_at desc limit %s", (limit,))
            return await cur.fetchall()

    async def close(self) -> None:
        if self.task and not self.task.done():
            self.task.cancel()
