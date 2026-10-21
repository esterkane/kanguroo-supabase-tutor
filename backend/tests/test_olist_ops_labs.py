"""Labs 05 (locks) and 06 (dead tuples) on real Olist data, driven through LabRunner like the tutor does."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from urllib.parse import urlparse, urlunparse
from uuid import uuid4

import psycopg
import pytest

from backend.tutor.lab_runner import LabRunner, lab_pool
from backend.tutor.tools import LabControlInput, RunLabSqlInput

SHIPPED = "54282e97f61c23b78330c15b154c867d"  # a real order still in status 'shipped'


@pytest.fixture
def lab_url(db_url: str) -> str:
    url = urlunparse(urlparse(db_url)._replace(path="/lab"))
    with psycopg.connect(url) as conn:
        if not (conn.execute("select to_regnamespace('olist')").fetchone() or [None])[0]:
            pytest.skip("Olist not imported (make olist)")
    return url


@pytest.fixture
async def runner(lab_url: str) -> AsyncIterator[LabRunner]:
    pool = lab_pool(lab_url, min_size=1, max_size=3)
    await pool.open()
    r = LabRunner(pool, lab_url, statement_timeout_ms=1500)
    yield r
    for slug in ("05-lock-contention", "06-dead-tuples"):  # leave both broken for learners
        await r.control(LabControlInput(slug=slug, action="install"), uuid4())
    await r.close_sessions()  # the stuck export session is the runner's; close it with the runner
    await pool.close()


def q(sql: str, **kw: object) -> RunLabSqlInput:
    return RunLabSqlInput(sql=sql, role="postgres", **kw)  # type: ignore[arg-type]


async def check(r: LabRunner, slug: str) -> bool:
    return bool((await r.control(LabControlInput(slug=slug, action="check"), uuid4()))["passed"])


async def test_lab05_real_blocker_diagnosed_and_fixed(runner: LabRunner) -> None:
    user = uuid4()
    await runner.control(LabControlInput(slug="05-lock-contention", action="install"), user)
    job = runner.sessions["job"]

    blocked = await runner.run_sql(q(f"select lab05.set_order_status('{SHIPPED}', 'delivered')"), user)
    assert blocked["sqlstate"] == "55P03", blocked  # canceling statement due to lock timeout

    activity = await runner.run_sql(q(
        "select pid, application_name, state, backend_xid::text as xid from pg_stat_activity "
        "where datname = current_database() and application_name = 'nightly-export'"), user)
    row = activity["rows"][0]
    assert row["pid"] == job.pid and row["state"] == "idle in transaction"
    xmax = await runner.run_sql(q(f"select xmax::text as xmax from lab05.orders where order_id = '{SHIPPED}'"), user)
    assert xmax["rows"][0]["xmax"] == row["xid"]  # the row is locked by the export's transaction
    assert not await check(runner, "05-lock-contention")

    refused = await runner.run_sql(q("select pg_terminate_backend(1)"), user)
    assert refused["refused"] and "not a session this lab opened" in refused["reason"]

    fix_export = await runner.run_sql(q(
        "create or replace function lab05.export_batch() returns setof lab05.orders language sql stable as "
        "$$ select * from lab05.orders where order_status = 'shipped' order by order_purchase_timestamp $$",
        persist=True), user)
    guardrail = await runner.run_sql(q("alter function lab05.set_order_status(text, text) set lock_timeout = '2s'",
                                       persist=True), user)
    assert fix_export["persisted"] and guardrail["persisted"]
    killed = await runner.run_sql(q(f"select pg_terminate_backend({job.pid})"), user)
    assert killed["rows"] == [{"pg_terminate_backend": True}] and "job" not in runner.sessions

    for _ in range(20):  # the backend exits asynchronously after the signal
        gone = await runner.run_sql(q("select count(*)::int as n from pg_stat_activity "
                                      "where application_name = 'nightly-export'"), user)
        if gone["rows"] == [{"n": 0}]:
            break
        await asyncio.sleep(0.1)
    works = await runner.run_sql(q(f"select lab05.set_order_status('{SHIPPED}', 'delivered')"), user)
    assert works["ok"], works
    assert await check(runner, "05-lock-contention")


async def test_lab06_dead_tuples_vacuumed(runner: LabRunner) -> None:
    user = uuid4()
    await runner.control(LabControlInput(slug="06-dead-tuples", action="install"), user)
    stats_sql = ("select n_live_tup::int as live, n_dead_tup::int as dead, last_autovacuum, "
                 "pg_table_size('lab06.orders')::bigint as bytes from pg_stat_user_tables "
                 "where relid = 'lab06.orders'::regclass")
    for _ in range(30):  # cumulative statistics are flushed asynchronously after the setup commits
        before = (await runner.run_sql(q(stats_sql), user))["rows"][0]
        if before["dead"] > 0:
            break
        await asyncio.sleep(0.1)
    assert before["dead"] >= 9 * 99441 and before["last_autovacuum"] is None
    opts = await runner.run_sql(q("select reloptions from pg_class where oid = 'lab06.orders'::regclass"), user)
    assert opts["rows"][0]["reloptions"] == ["autovacuum_enabled=false"]
    assert not await check(runner, "06-dead-tuples")

    in_tx = await runner.run_sql(q("vacuum lab06.orders"), user)
    assert in_tx["refused"] and "persist=true" in in_tx["reason"]
    reset = await runner.run_sql(q("alter table lab06.orders reset (autovacuum_enabled)", persist=True), user)
    vacuum = await runner.run_sql(q("vacuum lab06.orders", persist=True), user)
    assert reset["persisted"] and vacuum["persisted"] and vacuum["ok"], vacuum
    for _ in range(30):
        after = (await runner.run_sql(q(stats_sql), user))["rows"][0]
        if after["dead"] == 0:
            break
        await asyncio.sleep(0.1)
    assert after["dead"] == 0 and after["live"] == 99441
    assert after["bytes"] >= 0.5 * before["bytes"]  # plain VACUUM makes space reusable, it does not shrink much
    assert await check(runner, "06-dead-tuples")
