"""Labs 02, 03, 07, 08 (T2.3) on real Olist data, driven through LabRunner like the tutor and the lab console."""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlparse, urlunparse
from uuid import UUID, uuid4

import psycopg
import pytest

from backend.tutor.lab_runner import LabRunner, lab_pool
from backend.tutor.tools import LabControlInput, RunLabSqlInput

LOYAL = "b83579fb-095b-495e-3c5a-30fd7fcc0b62"  # app user of customer_unique_id 8d50f5ea... (17 real orders)
SLUGS = ("02-wrong-jwt-identity", "03-slow-rls-policy", "07-connection-exhaustion", "08-migration-drift")


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
    r = LabRunner(pool, lab_url)
    yield r
    for slug in SLUGS:  # leave every lab broken for learners
        await r.control(LabControlInput(slug=slug, action="install"), uuid4())
    await r.close_sessions()
    await pool.close()


async def ctl(r: LabRunner, slug: str, action: str, user: UUID) -> dict[str, Any]:
    return await r.control(LabControlInput(slug=slug, action=action), user)  # type: ignore[arg-type]


def as_user(sql: str, sub: str = LOYAL, **kw: Any) -> RunLabSqlInput:
    return RunLabSqlInput(sql=sql, role="authenticated", claims={"sub": sub, "role": "authenticated"}, **kw)


def pg(sql: str, **kw: Any) -> RunLabSqlInput:
    return RunLabSqlInput(sql=sql, role="postgres", **kw)


async def test_lab02_identity_by_order_key_hides_a_returning_customers_orders(runner: LabRunner) -> None:
    user, slug = uuid4(), "02-wrong-jwt-identity"
    assert (await ctl(runner, slug, "install", user))["ok"]
    seen = await runner.run_sql(as_user("select count(*) as n from lab02.orders"), user)
    assert seen["rows"] == [{"n": 1}]  # the symptom: 1 of 17
    who = await runner.run_sql(as_user("select auth.uid()::text as uid, customer_unique_id from lab02.profiles"), user)
    assert who["rows"] == [{"uid": LOYAL, "customer_unique_id": "8d50f5eadf50201ccdcedfb9e2ac8455"}]  # token is fine
    keys = await runner.run_sql(pg("select count(*) as orders, count(distinct customer_id) as ids from lab02.orders "
                                   "where customer_unique_id = '8d50f5eadf50201ccdcedfb9e2ac8455'"), user)
    assert keys["rows"] == [{"orders": 17, "ids": 17}]  # the real-data trap: one customer_id per order
    assert not (await ctl(runner, slug, "check", user))["passed"]
    fix = await runner.run_sql(pg(
        "alter policy orders_own on lab02.orders using (customer_unique_id = (select p.customer_unique_id "
        "from lab02.profiles p where p.user_id = (select auth.uid())))", persist=True), user)
    assert fix["persisted"], fix
    assert (await runner.run_sql(as_user("select count(*) as n from lab02.orders"), user))["rows"] == [{"n": 17}]
    assert (await ctl(runner, slug, "check", user))["passed"]


async def test_lab03_index_is_a_red_herring_select_wrapping_fixes_it(runner: LabRunner) -> None:
    user, slug = uuid4(), "03-slow-rls-policy"
    assert (await ctl(runner, slug, "install", user))["ok"]
    page = "select order_id from lab03.orders order by order_purchase_timestamp desc limit 20"
    assert (await runner.run_sql(as_user(page), user))["sqlstate"] == "57014"  # times out, as reported
    assert len((await runner.run_sql(pg(page), user))["rows"]) == 20  # without RLS: fast
    index = await runner.run_sql(pg("create index on lab03.orders (user_id)", persist=True), user)
    assert index["persisted"]
    assert (await runner.run_sql(as_user(page), user))["sqlstate"] == "57014"  # the forum fix changes nothing
    fix = await runner.run_sql(pg("alter policy orders_visible on lab03.orders using "
                                  "((select auth.uid()) = user_id or (select lab03.is_support_agent()))",
                                  persist=True), user)
    assert fix["persisted"]
    fast = await runner.run_sql(as_user(page, explain=True), user)
    assert fast["ok"] and len(fast["rows"]) == 20, fast
    assert "InitPlan" in str(fast["plan"])
    assert (await ctl(runner, slug, "check", user))["passed"]


async def test_lab07_role_connection_limit_real_53300_then_fixed(runner: LabRunner) -> None:
    user, slug = uuid4(), "07-connection-exhaustion"
    assert (await ctl(runner, slug, "install", user))["ok"]
    refused = await ctl(runner, slug, "reproduce", user)
    assert (refused["ok"], refused["stage"], refused["sqlstate"]) == (False, "connect", "53300"), refused
    assert 'too many connections for role "lab07_app"' in refused["message"]
    leaked = (await runner.run_sql(pg("select pid, state, application_name from pg_stat_activity "
                                      "where usename = 'lab07_app'"), user))["rows"]
    assert len(leaked) == 5 and {(r["state"], r["application_name"]) for r in leaked} == {("idle", "orders-api")}
    bulk = await runner.run_sql(pg("select pg_terminate_backend(pid) from pg_stat_activity "
                                   "where usename = 'lab07_app'"), user)
    assert bulk.get("refused")  # one own session per statement only
    other = await runner.run_sql(pg("alter role authenticated set statement_timeout = '1s'", persist=True), user)
    assert other.get("refused")  # only the lab's own role may get session timeouts
    for row in leaked:
        assert (await runner.run_sql(pg(f"select pg_terminate_backend({row['pid']})"), user))["ok"]
    assert (await runner.run_sql(pg("alter role lab07_app set idle_session_timeout = '1min'", persist=True),
                                 user))["persisted"]
    ok = await ctl(runner, slug, "reproduce", user)
    assert ok["ok"] and ok["rows"][0]["order_status"] == "canceled", ok
    assert ok["session_settings"]["idle_session_timeout"] == "1min"
    assert (await ctl(runner, slug, "check", user))["passed"]


async def test_lab08_repair_alone_is_not_enough(runner: LabRunner) -> None:
    user, slug = uuid4(), "08-migration-drift"
    assert (await ctl(runner, slug, "install", user))["ok"]
    push = await runner.run_sql(pg("select * from lab08.db_push()", persist=True), user)
    assert push["sqlstate"] == "42701", push  # column "delivery_eta" of relation "orders" already exists
    drift = await runner.run_sql(pg("select count(*) as differ from lab08.orders "
                                    "where delivery_eta is distinct from order_estimated_delivery_date::date"), user)
    assert drift["rows"][0]["differ"] > 90000  # the hotfix guessed purchase + 21 days
    repair = ("insert into lab08.schema_migrations select * from lab08.repo_migrations "
              "where version = '20261005120000'")
    assert (await runner.run_sql(pg(repair, persist=True), user))["persisted"]
    assert (await runner.run_sql(pg("select * from lab08.db_push()", persist=True), user))["rows"] == [
        {"version": "20261020100000", "name": "late_orders_view", "result": "applied"}]
    check = await ctl(runner, slug, "check", user)
    assert not check["passed"]  # history repaired and view deployed, but the column is still wrong
    assert any("not ok 2" in line for line in check["results"]) and any("not ok 3" in line for line in check["results"])

    assert (await ctl(runner, slug, "install", user))["ok"]  # the alternative path: drop the hand-made column
    assert (await runner.run_sql(pg("alter table lab08.orders drop column delivery_eta", persist=True), user))["persisted"]
    pushed = await runner.run_sql(pg("select version from lab08.db_push()", persist=True), user)
    assert [r["version"] for r in pushed["rows"]] == ["20261005120000", "20261020100000"]
    assert (await ctl(runner, slug, "check", user))["passed"]
