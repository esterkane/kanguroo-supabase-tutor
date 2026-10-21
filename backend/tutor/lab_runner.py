"""Lab runner: run_lab_sql and lab_control against the disposable `lab` database (ADR-008).

Every statement runs inside a transaction as a Supabase role with optional JWT claims, under a short
statement_timeout, and is rolled back unless the active lab declares that kind of step persistent
(lab.yaml `persistent_steps`). The lab database shares the Postgres cluster (and its roles) with the
tutor database, so the deny-list also refuses cluster-wide changes and anything that would leave the
sandbox (transaction control, role switching). Refusals are returned as data so the tutor can
explain them.

Named sessions ('a', 'b') keep one transaction open across calls for lock/long-transaction labs and
are force-rolled back after SESSION_TTL_S.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import yaml
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from backend.tutor.db import as_user
from backend.tutor.tools import LabControlInput, RunLabSqlInput

LABS = Path(__file__).resolve().parents[2] / "labs"
MAX_ROWS = 200
STATEMENT_TIMEOUT_MS = 5000
MAX_LAB_TIMEOUT_MS = 30000
SESSION_TTL_S = 120

DENY: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(?:create|drop|alter)\s+database\b", re.IGNORECASE), "database DDL is not allowed in the lab"),
    (re.compile(r"\b(?:create|drop|alter)\s+(?:role|user|group)\b", re.IGNORECASE),
     "roles are shared with the tutor database; role DDL is not allowed"),
    (re.compile(r"\bgrant\s+(?:anon|authenticated|service_role|postgres|authenticator|supabase\w*|pg_\w+)\s+to\b",
                re.IGNORECASE), "role membership is cluster-wide; only object privileges can be granted in the lab"),
    (re.compile(r"\balter\s+system\b", re.IGNORECASE), "ALTER SYSTEM changes the whole server"),
    (re.compile(r"\b(?:pg_terminate_backend|pg_cancel_backend|pg_reload_conf|pg_rotate_logfile)\b", re.IGNORECASE),
     "signalling other backends would affect the tutor itself"),
    (re.compile(r"\b(?:pg_read_file|pg_read_binary_file|pg_ls_dir|lo_import|lo_export|dblink\w*)\b", re.IGNORECASE),
     "server file and cross-database access is not allowed"),
    (re.compile(r"\bcopy\b[^;]*\b(?:program|from\s+'|to\s+')", re.IGNORECASE), "COPY to/from server files or programs"),
    (re.compile(r"\bcreate\s+extension\s+(?!(?:if\s+not\s+exists\s+)?(?:pgtap|vector)\b)", re.IGNORECASE),
     "only pgtap and vector extensions are allowed"),
    (re.compile(r"(?:^|;)\s*(?:commit|end|abort|rollback|begin|start\s+transaction|savepoint|release|"
                r"prepare\s+transaction)\b", re.IGNORECASE | re.MULTILINE),
     "transaction control is handled by the runner (use persist for declared steps)"),
    (re.compile(r"\b(?:set|reset)\s+(?:local\s+|session\s+)?(?:role|session\s+authorization)\b", re.IGNORECASE),
     "choose the role with the `role` argument instead"),
    (re.compile(r"\\!|\\c\b|\\connect\b", re.IGNORECASE), "psql meta-commands are not supported"),
]


def deny_reason(sql: str) -> str | None:
    for pattern, reason in DENY:
        if pattern.search(sql):
            return reason
    return None


def statement_kind(sql: str) -> str:
    m = re.match(r"\s*(?:--[^\n]*\n\s*)*(\w+)", sql)
    return m.group(1).lower() if m else ""


def single_statement(sql: str) -> bool:
    return ";" not in sql.strip().rstrip(";")


def parse_tap(lines: list[str]) -> dict[str, Any]:
    tap = [ln for ln in lines if re.match(r"^(?:not )?ok \d+", ln)]
    plan = next((ln for ln in lines if re.match(r"^1\.\.\d+$", ln)), None)
    planned = int(plan.split("..")[1]) if plan else -1
    passed = bool(tap) and all(ln.startswith("ok") for ln in tap) and len(tap) == planned
    return {"passed": passed, "planned": planned, "results": tap}


# ----------------------------------------------------------------------------- labs on disk
@dataclass(frozen=True)
class LabSpec:
    slug: str
    phase: str
    title: str
    path: Path
    persistent_steps: tuple[str, ...] = ()
    statement_timeout_ms: int = STATEMENT_TIMEOUT_MS
    hypotheses: tuple[dict[str, str], ...] = ()
    requires: tuple[str, ...] = ()  # dataset schemas in the lab DB, e.g. olist

    @property
    def schema(self) -> str:
        return "lab" + self.slug.split("-", 1)[0]  # 01-rls-vs-grant -> lab01

    def hints(self) -> list[str]:
        text = (self.path / "hints.md").read_text(encoding="utf-8")
        return [re.sub(r"^\d+\.\s*", "", ln).strip() for ln in text.splitlines() if re.match(r"^\d+\.", ln)]


def load_labs(root: Path = LABS) -> dict[str, LabSpec]:
    labs = {}
    for path in sorted(root.glob("*/lab.yaml")):
        spec = yaml.safe_load(path.read_text(encoding="utf-8"))
        timeout = int(spec.get("statement_timeout_s", STATEMENT_TIMEOUT_MS / 1000) * 1000)
        labs[spec["slug"]] = LabSpec(
            slug=spec["slug"], phase=spec["phase"], title=spec["title"], path=path.parent,
            persistent_steps=tuple(s.lower() for s in spec.get("persistent_steps", [])),
            statement_timeout_ms=min(timeout, MAX_LAB_TIMEOUT_MS),
            hypotheses=tuple(spec.get("hypotheses", [])),
            requires=tuple(spec.get("requires", [])),
        )
    return labs


# ----------------------------------------------------------------------------- runner state
@dataclass
class ActiveLab:
    spec: LabSpec
    lab_run_id: UUID | None = None
    hints_used: int = 0


@dataclass
class NamedSession:
    conn: AsyncConnection
    opened: float = field(default_factory=time.monotonic)
    expiry: asyncio.Task[None] | None = None


async def _reset(conn: AsyncConnection) -> None:
    await conn.execute("discard all")


def lab_pool(lab_url: str, **kwargs: Any) -> AsyncConnectionPool:
    """Pool for the lab database: autocommit connections, session state discarded on return."""
    return AsyncConnectionPool(lab_url, kwargs={"autocommit": True}, reset=_reset, open=False, **kwargs)


class LabRunner:
    """Implements backend.tutor.tools.LabTools for one tutor session."""

    def __init__(
        self,
        pool: AsyncConnectionPool,
        lab_url: str,
        app_pool: AsyncConnectionPool | None = None,
        session_id: UUID | None = None,
        labs: dict[str, LabSpec] | None = None,
        statement_timeout_ms: int = STATEMENT_TIMEOUT_MS,
    ) -> None:
        self.pool = pool
        self.lab_url = lab_url
        self.app_pool = app_pool
        self.session_id = session_id
        self.labs = labs if labs is not None else load_labs()
        self.default_timeout_ms = statement_timeout_ms
        self.active: ActiveLab | None = None
        self.sessions: dict[str, NamedSession] = {}

    # ------------------------------------------------------------------ run_lab_sql
    def _timeout_ms(self) -> int:
        if self.active and self.active.spec.statement_timeout_ms != STATEMENT_TIMEOUT_MS:
            return self.active.spec.statement_timeout_ms
        return self.default_timeout_ms

    def _lock_timeout_ms(self) -> int:
        # Below statement_timeout so a blocked statement reports 55P03 (lock timeout), the clearer evidence.
        return max(1, self._timeout_ms() * 4 // 5)

    async def _prepare(self, conn: AsyncConnection, args: RunLabSqlInput) -> None:
        await conn.execute(f"set local statement_timeout = {self._timeout_ms()}")
        await conn.execute(f"set local lock_timeout = {self._lock_timeout_ms()}")
        if args.role != "postgres":
            await conn.execute(f"set local role {args.role}")  # Literal-validated: anon | authenticated
        if args.claims is not None:
            await conn.execute("select set_config('request.jwt.claims', %s, true)", (json.dumps(args.claims),))

    async def _execute(self, conn: AsyncConnection, sql: str, out: dict[str, Any]) -> None:
        cur = conn.cursor(row_factory=dict_row)
        await cur.execute(sql.encode())  # bytes: simple query protocol, several statements allowed
        if cur.description is not None:
            rows = await cur.fetchmany(MAX_ROWS + 1)
            out["truncated"] = len(rows) > MAX_ROWS
            out["rows"] = rows[:MAX_ROWS]
        out["row_count"] = cur.rowcount

    async def _explain(self, conn: AsyncConnection, sql: str, out: dict[str, Any]) -> None:
        if not single_statement(sql):
            out["explain_note"] = "EXPLAIN needs a single statement"
            return
        try:
            async with conn.transaction():  # savepoint: EXPLAIN ANALYZE executes the statement again
                cur = await conn.execute(f"explain (analyze, buffers, format json) {sql.strip().rstrip(';')}")
                row = await cur.fetchone()
                out["plan"] = row[0] if row else None
                raise psycopg.Rollback()
        except psycopg.Error as e:
            out["explain_note"] = f"EXPLAIN failed: {e.diag.message_primary}"

    @staticmethod
    def _error(out: dict[str, Any], e: psycopg.Error) -> None:
        out.update(ok=False, sqlstate=e.sqlstate, message=e.diag.message_primary,
                   detail=e.diag.message_detail, hint=e.diag.message_hint)

    async def run_sql(self, args: RunLabSqlInput, user_id: UUID) -> dict[str, Any]:
        sql = args.sql.strip()
        out: dict[str, Any] = {"ok": True, "role": args.role, "claims": args.claims,
                               "statement": statement_kind(sql), "rows": [], "truncated": False,
                               "row_count": None, "persisted": False, "database": "lab"}
        if reason := deny_reason(sql):
            return {"ok": False, "refused": True, "reason": reason, "role": args.role, "database": "lab"}
        if args.session:
            return await self._run_in_session(args, sql, out, user_id)

        persist_allowed = bool(self.active and out["statement"] in self.active.spec.persistent_steps)
        if args.persist and not persist_allowed:
            declared = list(self.active.spec.persistent_steps) if self.active else []
            out["persist_note"] = (f"not persisted: '{out['statement']}' is not a declared persistent step "
                                   f"(declared: {declared or 'none'}; install a lab first)")
        started = time.monotonic()
        async with self.pool.connection() as conn:
            try:
                async with conn.transaction() as tx:
                    await self._prepare(conn, args)
                    try:
                        async with conn.transaction():  # savepoint around the learner's statement
                            await self._execute(conn, sql, out)
                    except psycopg.Error as e:
                        self._error(out, e)
                    if out["ok"] and args.explain:
                        await self._explain(conn, sql, out)
                    if not (out["ok"] and args.persist and persist_allowed):
                        raise psycopg.Rollback(tx)
                    out["persisted"] = True
            except psycopg.Error as e:  # setup failed (e.g. bad claims)
                self._error(out, e)
        out["ms"] = round((time.monotonic() - started) * 1000, 1)
        await self._log(user_id, args, sql, out)
        return out

    # ------------------------------------------------------------------ named sessions
    async def _run_in_session(self, args: RunLabSqlInput, sql: str, out: dict[str, Any],
                              user_id: UUID) -> dict[str, Any]:
        name = args.session or "a"
        session = self.sessions.get(name)
        if session is None:
            conn = await AsyncConnection.connect(self.lab_url, autocommit=False)
            await conn.execute(f"set statement_timeout = {self._timeout_ms()}")
            await conn.execute(f"set lock_timeout = {self._lock_timeout_ms()}")
            session = self.sessions[name] = NamedSession(conn)
            session.expiry = asyncio.create_task(self._expire(name, session))
        conn = session.conn
        out["session"] = name
        out["session_open_s"] = round(time.monotonic() - session.opened, 1)
        started = time.monotonic()
        try:
            await conn.execute(f"set local role {args.role}" if args.role != "postgres" else "reset role")
            if args.claims is not None:
                await conn.execute("select set_config('request.jwt.claims', %s, true)",
                                   (json.dumps(args.claims),))
            async with conn.transaction():  # savepoint: an error keeps the session's transaction usable
                await self._execute(conn, sql, out)
        except psycopg.Error as e:
            self._error(out, e)
        out["ms"] = round((time.monotonic() - started) * 1000, 1)
        out["note"] = (f"session '{name}' keeps its transaction (and locks) open until "
                       f"lab_control reset or {SESSION_TTL_S}s")
        await self._log(user_id, args, sql, out)
        return out

    async def _expire(self, name: str, session: NamedSession) -> None:
        await asyncio.sleep(SESSION_TTL_S)
        if self.sessions.get(name) is session:
            await self._close_session(name)

    async def _close_session(self, name: str) -> None:
        session = self.sessions.pop(name, None)
        if session is None:
            return
        if session.expiry and session.expiry is not asyncio.current_task():
            session.expiry.cancel()
        try:
            await session.conn.rollback()
        finally:
            await session.conn.close()

    async def close_sessions(self) -> None:
        for name in list(self.sessions):
            await self._close_session(name)

    # ------------------------------------------------------------------ lab_control
    async def control(self, args: LabControlInput, user_id: UUID) -> dict[str, Any]:
        handlers: dict[str, Callable[[LabSpec, UUID], Awaitable[dict[str, Any]]]] = {
            "install": self._install, "reset": self._install, "status": self._status,
            "hint": self._hint, "check": self._check,
        }
        if args.action == "list":
            return {"labs": [{"slug": s.slug, "phase": s.phase, "title": s.title} for s in self.labs.values()],
                    "active": self.active.spec.slug if self.active else None}
        spec = self.labs.get(args.slug or "")
        if spec is None:
            return {"ok": False, "error": f"unknown lab {args.slug!r}", "labs": sorted(self.labs)}
        if args.action != "install" and args.action != "reset" and (not self.active or self.active.spec != spec):
            return {"ok": False, "error": f"lab {spec.slug} is not the active lab; install it first"}
        return await handlers[args.action](spec, user_id)

    async def _install(self, spec: LabSpec, user_id: UUID) -> dict[str, Any]:
        await self.close_sessions()
        setup = (spec.path / "setup.sql").read_text(encoding="utf-8")
        async with self.pool.connection() as conn:
            for dataset in spec.requires:
                found = await (await conn.execute("select to_regnamespace(%s)", (dataset,))).fetchone()
                if not (found and found[0]):
                    return {"ok": False, "error": f"lab {spec.slug} needs the {dataset} dataset in the lab database",
                            "learner_action": f"run `make {dataset}` in the project folder, then install the lab again"}
            await conn.execute(f"drop schema if exists {spec.schema} cascade".encode())
            await conn.execute(setup.encode())
        self.active = ActiveLab(spec, lab_run_id=await self._start_run(spec, user_id))
        return {"ok": True, "installed": spec.slug, "title": spec.title,
                "scenario": (spec.path / "README.md").read_text(encoding="utf-8")}

    async def _status(self, spec: LabSpec, user_id: UUID) -> dict[str, Any]:
        assert self.active is not None
        return {
            "ok": True, "lab": spec.slug, "title": spec.title, "phase": spec.phase,
            "hints_used": self.active.hints_used, "hints_total": len(spec.hints()),
            "open_sessions": sorted(self.sessions),
            "scenario": (spec.path / "README.md").read_text(encoding="utf-8"),
            "coaching_for_tutor_only": {
                "note": "Do not reveal these; use them to pick the next discriminating question.",
                "hypotheses": list(spec.hypotheses),
            },
        }

    async def _hint(self, spec: LabSpec, user_id: UUID) -> dict[str, Any]:
        assert self.active is not None
        hints = spec.hints()
        if self.active.hints_used >= len(hints):
            return {"ok": True, "hint": None, "note": "all hints revealed; offer 'show me' or the solution walk"}
        self.active.hints_used += 1
        await self._update_run("hints_used = %s", (self.active.hints_used,), user_id)
        return {"ok": True, "hint_number": self.active.hints_used, "hint": hints[self.active.hints_used - 1],
                "remaining": len(hints) - self.active.hints_used}

    async def _check(self, spec: LabSpec, user_id: UUID) -> dict[str, Any]:
        checks = (spec.path / "checks.sql").read_text(encoding="utf-8")
        lines: list[str] = []
        try:
            async with self.pool.connection() as conn:
                cur = conn.cursor()
                await cur.execute(checks.encode())
                while True:
                    if cur.description:
                        lines += [str(v) for row in await cur.fetchall() for v in row if isinstance(v, str)]
                    if not cur.nextset():
                        break
        except psycopg.Error as e:
            return {"ok": True, "passed": False, "sqlstate": e.sqlstate, "message": e.diag.message_primary}
        result = parse_tap(lines)
        if result["passed"]:
            await self._update_run("outcome = 'solved', finished_at = now()", (), user_id)
        return {"ok": True, **result}

    # ------------------------------------------------------------------ tutor.lab_run bookkeeping
    async def _start_run(self, spec: LabSpec, user_id: UUID) -> UUID | None:
        if self.app_pool is None or self.session_id is None:
            return None
        async with as_user(self.app_pool, user_id) as conn:
            cur = await conn.execute(
                "insert into tutor.lab_run (session_id, lab_slug) values (%s, %s) returning id",
                (self.session_id, spec.slug))
            row = await cur.fetchone()
            return row[0] if row else None

    async def _update_run(self, assignment: str, params: tuple[Any, ...], user_id: UUID) -> None:
        if self.app_pool is None or self.active is None or self.active.lab_run_id is None:
            return
        async with as_user(self.app_pool, user_id) as conn:
            await conn.execute(f"update tutor.lab_run set {assignment} where id = %s",
                               (*params, self.active.lab_run_id))

    async def _log(self, user_id: UUID, args: RunLabSqlInput, sql: str, out: dict[str, Any]) -> None:
        entry = {"role": args.role, "sql_sha256": sha256(sql.encode()).hexdigest()[:16],
                 "statement": out.get("statement"), "sqlstate": out.get("sqlstate"), "ms": out.get("ms"),
                 "session": args.session, "persisted": out.get("persisted", False)}
        await self._update_run("tests = tests || %s::jsonb", (json.dumps([entry]),), user_id)
