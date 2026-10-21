"""Olist dataset + the labs built on it, driven through LabRunner (skips unless `make olist` ran)."""
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace
from urllib.parse import urlparse, urlunparse
from uuid import uuid4

import psycopg
import pytest

from backend.tutor.lab_runner import LabRunner, lab_pool
from backend.tutor.tools import LabControlInput, RunLabSqlInput

CUSTOMER = "8d50f5eadf50201ccdcedfb9e2ac8455"  # real customer with the most orders (17)


@pytest.fixture
def lab_url(db_url: str) -> str:
    url = urlunparse(urlparse(db_url)._replace(path="/lab"))
    with psycopg.connect(url) as conn:
        if not (conn.execute("select to_regnamespace('olist')").fetchone() or [None])[0]:
            pytest.skip("Olist not imported (make olist)")
    return url


@pytest.fixture
async def runner(lab_url: str) -> AsyncIterator[LabRunner]:
    pool = lab_pool(lab_url, min_size=1, max_size=2)
    await pool.open()
    r = LabRunner(pool, lab_url)
    yield r
    await r.close_sessions()
    for slug in ("04-missing-index", "09-revenue-join-fanout"):  # leave both labs broken for learners
        await r.control(LabControlInput(slug=slug, action="install"), uuid4())
    await pool.close()


def test_import_matches_the_csvs(lab_url: str) -> None:
    with psycopg.connect(lab_url) as conn:
        counts: dict[str, int] = dict(conn.execute("""
            select 'orders', count(*) from olist.orders union all
            select 'order_items', count(*) from olist.order_items union all
            select 'order_payments', count(*) from olist.order_payments union all
            select 'customers', count(*) from olist.customers union all
            select 'app_users', count(*) from olist.app_users""").fetchall())
        distinct_people = conn.execute("select count(distinct customer_unique_id) from olist.customers").fetchone()
    assert counts["orders"] == counts["customers"] == 99441  # Olist: one customer_id per order
    assert counts["order_items"] == 112650 and counts["order_payments"] == 103886
    assert distinct_people and counts["app_users"] == distinct_people[0] == 96096


async def test_lab09_fanout_is_real_and_fixable(runner: LabRunner) -> None:
    user = uuid4()
    installed = await runner.control(LabControlInput(slug="09-revenue-join-fanout", action="install"), user)
    assert installed["ok"] and "28 %" in installed["scenario"]
    total = await runner.run_sql(RunLabSqlInput(sql="select sum(revenue)::text as v from lab09.monthly_revenue",
                                                role="postgres"), user)
    assert total["rows"] == [{"v": "19776160.44"}]  # the number in the customer report
    assert (await runner.control(LabControlInput(slug="09-revenue-join-fanout", action="check"), user))["passed"] is False

    fix = runner.labs["09-revenue-join-fanout"].path.joinpath("solution.sql").read_text()
    view = fix[fix.index("create or replace view"):fix.index("-- AFTER")]
    out = await runner.run_sql(RunLabSqlInput(sql=view, role="postgres", persist=True), user)
    assert out["ok"] and out["persisted"], out
    fixed = await runner.run_sql(RunLabSqlInput(sql="select sum(revenue)::text as v from lab09.monthly_revenue",
                                                role="postgres"), user)
    assert fixed["rows"] == [{"v": "15422461.77"}]  # equals what was actually paid
    assert (await runner.control(LabControlInput(slug="09-revenue-join-fanout", action="check"), user))["passed"] is True


async def test_lab04_index_removes_seq_scan_and_sort(runner: LabRunner) -> None:
    user = uuid4()
    await runner.control(LabControlInput(slug="04-missing-index", action="install"), user)
    page = (f"select order_id, order_status, order_purchase_timestamp, total from lab04.orders "
            f"where customer_unique_id = '{CUSTOMER}' order by order_purchase_timestamp desc limit 20")

    def nodes(plan: dict) -> list[str]:
        out, node = [], plan["Plan"]
        while node:
            out.append(node["Node Type"])
            node = (node.get("Plans") or [None])[0]
        return out

    before = await runner.run_sql(RunLabSqlInput(sql=page, role="postgres", explain=True), user)
    assert {"Seq Scan", "Sort"} <= set(nodes(before["plan"][0])) and len(before["rows"]) == 20
    single = await runner.run_sql(RunLabSqlInput(
        sql="create index on lab04.orders (customer_unique_id)", role="postgres", persist=True), user)
    assert single["persisted"]
    still_sorting = await runner.run_sql(RunLabSqlInput(sql=page, role="postgres", explain=True), user)
    assert "Sort" in nodes(still_sorting["plan"][0])  # hint 4: one-column index still sorts
    await runner.run_sql(RunLabSqlInput(
        sql="create index lab04_orders_customer_purchase_idx on lab04.orders "
            "(customer_unique_id, order_purchase_timestamp desc)", role="postgres", persist=True), user)
    after = await runner.run_sql(RunLabSqlInput(sql=page, role="postgres", explain=True), user)
    assert nodes(after["plan"][0]) == ["Limit", "Index Scan"]
    assert after["rows"] == before["rows"]  # same 20 rows for the page
    assert (await runner.control(LabControlInput(slug="04-missing-index", action="check"), user))["passed"] is True


async def test_missing_dataset_is_reported_not_crashed(runner: LabRunner) -> None:
    spec = replace(runner.labs["09-revenue-join-fanout"], requires=("no_such_dataset",))
    runner.labs[spec.slug] = spec
    out = await runner.control(LabControlInput(slug=spec.slug, action="install"), uuid4())
    assert out["ok"] is False and "make no_such_dataset" in out["learner_action"]
    runner.labs[spec.slug] = replace(spec, requires=("olist",))
