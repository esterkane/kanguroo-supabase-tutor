"""LabRunner against the local `lab` database with lab 01 (rls-vs-grant). Skips without the stack."""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlparse, urlunparse
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg_pool import AsyncConnectionPool

from backend.tutor import tools as t
from backend.tutor.db import as_user
from backend.tutor.lab_runner import LabRunner, deny_reason, lab_pool, parse_tap, statement_kind
from backend.tutor.tools import LabControlInput, RunLabSqlInput

USER_A = "11111111-1111-1111-1111-111111111111"
CLAIMS_A = {"sub": USER_A, "role": "authenticated"}


@pytest.fixture
def lab_url(db_url: str) -> str:
    return urlunparse(urlparse(db_url)._replace(path="/lab"))


@pytest.fixture
async def runner(lab_url: str) -> AsyncIterator[LabRunner]:
    pool = lab_pool(lab_url, min_size=1, max_size=3)
    await pool.open()
    r = LabRunner(pool, lab_url, statement_timeout_ms=1000)
    await r.control(LabControlInput(slug="01-rls-vs-grant", action="install"), uuid4())
    yield r
    await r.close_sessions()
    await r.control(LabControlInput(slug="01-rls-vs-grant", action="install"), uuid4())  # leave it broken
    await pool.close()


def sql(text: str, **kw: Any) -> RunLabSqlInput:
    return RunLabSqlInput(sql=text, **kw)


# ----------------------------------------------------------------------------- pure helpers
@pytest.mark.parametrize("bad", [
    "drop database postgres", "create role hacker login", "grant authenticated to anon",
    "alter system set work_mem = '1GB'", "select pg_terminate_backend(123)", "select pg_read_file('/etc/passwd')",
    "copy lab01.orders to '/tmp/x'", "create extension pg_net", "commit", "select 1; rollback",
    "set role postgres", "reset role", "set session authorization postgres", "set local role supabase_admin",
    "set local role authenticator",
])
def test_deny_list(bad: str) -> None:
    assert deny_reason(bad) is not None


@pytest.mark.parametrize("ok", [
    "select * from lab01.orders", "grant select on lab01.orders to authenticated",
    "create extension if not exists pgtap", "explain select 1",
    "select set_config('request.jwt.claims', '{}', true)", "create index on lab01.orders (created_at)",
    "create table t (id int); set local role authenticated; select count(*) from t",
])
def test_deny_list_allows_lab_work(ok: str) -> None:
    assert deny_reason(ok) is None


def test_statement_kind_and_tap() -> None:
    assert statement_kind("-- why\n  GRANT select on x to y") == "grant"
    assert parse_tap(["1..2", "ok 1 - a", "ok 2 - b"])["passed"]
    assert not parse_tap(["1..2", "ok 1 - a"])["passed"]
    assert not parse_tap(["1..1", "not ok 1 - a"])["passed"]


# ----------------------------------------------------------------------------- run_sql
async def test_lab01_symptom_as_authenticated(runner: LabRunner) -> None:
    out = await runner.run_sql(sql("select * from lab01.orders", claims=CLAIMS_A), uuid4())
    assert out["ok"] is False and out["sqlstate"] == "42501"
    assert "permission denied for table orders" in out["message"]
    assert out["database"] == "lab" and out["persisted"] is False


async def test_postgres_role_sees_all_rows_and_rows_are_capped(runner: LabRunner) -> None:
    out = await runner.run_sql(sql("select count(*)::int as n from lab01.orders", role="postgres"), uuid4())
    assert out["ok"] and out["rows"] == [{"n": 20}]
    big = await runner.run_sql(sql("select g from generate_series(1, 300) g", role="postgres"), uuid4())
    assert len(big["rows"]) == 200 and big["truncated"] is True


async def test_declared_persistent_step_fixes_lab_and_rls_still_filters(runner: LabRunner) -> None:
    fix = await runner.run_sql(sql("grant select on lab01.orders to authenticated", role="postgres",
                                   persist=True), uuid4())
    assert fix["ok"] and fix["persisted"] is True
    after = await runner.run_sql(sql("select count(*)::int as n from lab01.orders", claims=CLAIMS_A), uuid4())
    assert after["rows"] == [{"n": 10}]  # GRANT lets the policy run; RLS keeps user A to own rows
    check = await runner.control(LabControlInput(slug="01-rls-vs-grant", action="check"), uuid4())
    assert check["passed"] is True


async def test_undeclared_persist_is_rolled_back(runner: LabRunner) -> None:
    out = await runner.run_sql(sql("delete from lab01.orders where true", role="postgres", persist=True), uuid4())
    assert out["ok"] and out["persisted"] is False and "not a declared persistent step" in out["persist_note"]
    count = await runner.run_sql(sql("select count(*)::int as n from lab01.orders", role="postgres"), uuid4())
    assert count["rows"] == [{"n": 20}]


async def test_explain_returns_json_plan_and_changes_nothing(runner: LabRunner) -> None:
    out = await runner.run_sql(sql("select * from lab01.orders where user_id = '" + USER_A + "'",
                                   role="postgres", explain=True), uuid4())
    plan = out["plan"]
    assert isinstance(plan, list) and "Plan" in plan[0] and "Execution Time" in plan[0]


async def test_statement_timeout(runner: LabRunner) -> None:
    out = await runner.run_sql(sql("select pg_sleep(3)", role="postgres"), uuid4())
    assert out["sqlstate"] == "57014" and out["ms"] < 2500


async def test_refusal_is_data_not_exception(runner: LabRunner) -> None:
    out = await runner.run_sql(sql("drop database lab"), uuid4())
    assert out == {"ok": False, "refused": True, "reason": "database DDL is not allowed in the lab",
                   "role": "authenticated", "database": "lab"}


async def test_named_sessions_hold_locks_until_reset(runner: LabRunner) -> None:
    lock = await runner.run_sql(sql("lock table lab01.orders in access exclusive mode", role="postgres",
                                    session="a"), uuid4())
    assert lock["ok"] and lock["session"] == "a"
    blocked = await runner.run_sql(sql("select count(*) from lab01.orders", role="postgres", session="b"), uuid4())
    assert blocked["sqlstate"] == "55P03"  # lock_timeout: session a still holds ACCESS EXCLUSIVE
    again = await runner.run_sql(sql("select 1 as one", role="postgres", session="b"), uuid4())
    assert again["ok"] and again["rows"] == [{"one": 1}]  # an error doesn't poison the session
    await runner.control(LabControlInput(slug="01-rls-vs-grant", action="reset"), uuid4())
    assert runner.sessions == {}
    free = await runner.run_sql(sql("select count(*)::int as n from lab01.orders", role="postgres"), uuid4())
    assert free["rows"] == [{"n": 20}]


# ----------------------------------------------------------------------------- lab_control
async def test_control_list_status_hints_check(runner: LabRunner) -> None:
    listing = await runner.control(LabControlInput(action="list"), uuid4())
    assert {"slug": "01-rls-vs-grant", "phase": "D", "title": runner.labs["01-rls-vs-grant"].title} in listing["labs"]
    status = await runner.control(LabControlInput(slug="01-rls-vs-grant", action="status"), uuid4())
    assert status["hints_total"] == 5 and "Customer report" in status["scenario"]
    assert "solution" not in json.dumps(status).lower().replace("solution.sql", "")
    hints = [await runner.control(LabControlInput(slug="01-rls-vs-grant", action="hint"), uuid4())
             for _ in range(6)]
    assert [h.get("hint_number") for h in hints[:5]] == [1, 2, 3, 4, 5] and hints[5]["hint"] is None
    assert "permission denied" in hints[0]["hint"]
    broken = await runner.control(LabControlInput(slug="01-rls-vs-grant", action="check"), uuid4())
    assert broken["passed"] is False
    other = await runner.control(LabControlInput(slug="99-nope", action="status"), uuid4())
    assert other["ok"] is False


async def test_dispatch_through_tools(runner: LabRunner) -> None:
    ctx = t.ToolContext(user_id=uuid4(), retriever=None, ledger=None, lab=runner)  # type: ignore[arg-type]
    res = await t.dispatch("run_lab_sql", {"sql": "select * from lab01.orders", "claims": CLAIMS_A}, ctx,
                           t.TurnBudget())
    assert not res.is_error and json.loads(res.content)["sqlstate"] == "42501"
    res = await t.dispatch("lab_control", {"action": "hint"}, ctx, t.TurnBudget())
    assert res.is_error and "needs a slug" in res.content


# ----------------------------------------------------------------------------- tutor.lab_run bookkeeping
@pytest.fixture
async def session_row(pool: AsyncConnectionPool, db_url: str) -> AsyncIterator[tuple[UUID, UUID]]:
    user = uuid4()
    async with as_user(pool, user) as conn:
        cur = await conn.execute("insert into tutor.session (objective) values ('lab test') returning id")
        row = await cur.fetchone()
        assert row is not None
    yield user, row[0]
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute("delete from tutor.session where id = %s", (row[0],))


async def test_lab_run_records_tests_hints_and_outcome(runner: LabRunner, pool: AsyncConnectionPool,
                                                       session_row: tuple[UUID, UUID]) -> None:
    user, session_id = session_row
    # Own runner: the shared fixture's teardown must not write through `pool` after it is closed.
    runner = LabRunner(runner.pool, runner.lab_url, app_pool=pool, session_id=session_id, statement_timeout_ms=1000)
    await runner.control(LabControlInput(slug="01-rls-vs-grant", action="install"), user)
    await runner.run_sql(sql("select * from lab01.orders", claims=CLAIMS_A), user)
    await runner.control(LabControlInput(slug="01-rls-vs-grant", action="hint"), user)
    await runner.run_sql(sql("grant select on lab01.orders to authenticated", role="postgres", persist=True), user)
    await runner.control(LabControlInput(slug="01-rls-vs-grant", action="check"), user)
    async with as_user(pool, user) as conn:
        cur = await conn.execute("select tests, hints_used, outcome from tutor.lab_run where session_id = %s",
                                 (session_id,))
        tests, hints_used, outcome = await cur.fetchone() or (None, None, None)
    assert [(x["role"], x["sqlstate"], x["persisted"]) for x in tests] == \
        [("authenticated", "42501", False), ("postgres", None, True)]
    assert hints_used == 1 and outcome == "solved"
    async with as_user(pool, uuid4()) as conn:  # another learner cannot see the run
        cur = await conn.execute("select count(*) from tutor.lab_run where session_id = %s", (session_id,))
        assert (await cur.fetchone() or [None])[0] == 0


async def test_set_local_role_switches_within_one_statement(runner: LabRunner) -> None:
    out = await runner.run_sql(sql(
        "create table lab01.k_demo (id int); insert into lab01.k_demo values (1); "
        "set local role authenticated; select count(*)::int as n from lab01.k_demo", role="postgres"), uuid4())
    assert out["ok"] is False and out["sqlstate"] == "42501"  # authenticated has no GRANT on the new table
    gone = await runner.run_sql(sql("select to_regclass('lab01.k_demo')::text as t", role="postgres"), uuid4())
    assert gone["rows"] == [{"t": None}]  # rolled back: nothing persisted


async def test_readme_evidence_block_runs_as_written(runner: LabRunner) -> None:
    readme = (runner.labs["01-rls-vs-grant"].path / "README.md").read_text()
    block = readme.split("```sql", 1)[1].split("```", 1)[0]
    assert block.strip().startswith("begin;") and block.strip().endswith("rollback;")
    out = await runner.run_sql(sql(block, role="postgres"), uuid4())
    assert out["sqlstate"] == "42501"  # same evidence as in psql, without the transaction wrapper
    for still_refused in ("begin; select 1; commit;", "select 1; rollback;", "begin; select 1; rollback; select 2;"):
        assert (await runner.run_sql(sql(still_refused), uuid4())).get("refused") is True, still_refused
