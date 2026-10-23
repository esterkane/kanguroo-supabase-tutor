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
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import yaml
from psycopg import AsyncConnection, sql
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from backend.tutor.db import as_user
from backend.tutor.tools import LabControlInput, RunLabSqlInput

LABS = Path(__file__).resolve().parents[2] / "labs"
MAX_ROWS = 200
STATEMENT_TIMEOUT_MS = 5000
MAX_LAB_TIMEOUT_MS = 30000
SESSION_TTL_S = 120
MAX_SESSION_TTL_S = 900  # lock labs keep their blocker open long enough to investigate

DENY: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(?:create|drop|alter)\s+database\b", re.IGNORECASE), "database DDL is not allowed in the lab"),
    # Exception: session timeouts on a role a lab created itself (lab07_app), the documented per-user setting.
    (re.compile(r"\b(?:create|drop|alter)\s+(?:role|user|group)\b(?!\s+lab\d\d_\w+\s+(?:set|reset)\s+"
                r"(?:idle_session_timeout|idle_in_transaction_session_timeout|statement_timeout)\b)", re.IGNORECASE),
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
    (re.compile(r"\bset\s+(?:session\s+)?role\b|\breset\s+role\b|\bsession\s+authorization\b", re.IGNORECASE),
     "use the `role` argument, or SET LOCAL ROLE inside the statement"),
    (re.compile(r"\\!|\\c\b|\\connect\b", re.IGNORECASE), "psql meta-commands are not supported"),
]


# Signalling a backend is allowed only for sessions this runner opened in the lab DB (see _signal_session).
SIGNAL_OWN = re.compile(r"select\s+pg_(terminate|cancel)_backend\(\s*(\d+)\s*\)\s*;?", re.IGNORECASE)
# Statements PostgreSQL refuses inside a transaction block; run in autocommit, only as declared persistent steps.
NO_TRANSACTION = {"vacuum"}


# SET LOCAL ROLE is transaction-scoped (and the runner rolls back), so switching between the roles the tool
# offers inside one statement is fine, e.g. set up as postgres, then query as authenticated.
LOCAL_ROLE = re.compile(r"\bset\s+local\s+role\s+\"?(\w+)", re.IGNORECASE)
SWITCHABLE_ROLES = {"anon", "authenticated", "service_role", "postgres"}
# Roles a lab's setup.sql creates for itself; the runner gives them a fresh random password at install.
LAB_LOGIN_ROLE = re.compile(r"^lab\d\d_\w+$")


def deny_reason(sql: str) -> str | None:
    for role in LOCAL_ROLE.findall(sql):
        if role.lower() not in SWITCHABLE_ROLES:
            return f"SET LOCAL ROLE is limited to {', '.join(sorted(SWITCHABLE_ROLES))}"
    for pattern, reason in DENY:
        if pattern.search(sql):
            return reason
    return None


# Lab READMEs show psql-style evidence blocks (begin; ...; rollback;). The runner rolls back anyway, so exactly
# that wrapper is unwrapped; any other transaction control stays refused by DENY.
ROLLBACK_WRAPPER = re.compile(r"^\s*(?:begin|start\s+transaction)\s*;(?P<body>.*?)(?:rollback|abort)\s*;?\s*$",
                              re.IGNORECASE | re.DOTALL)


def unwrap_rollback(sql: str) -> str:
    m = ROLLBACK_WRAPPER.match(sql)
    return m.group("body").strip() if m else sql


def statement_kind(sql: str) -> str:
    m = re.match(r"\s*(?:--[^\n]*\n\s*)*(\w+)", sql)
    return m.group(1).lower() if m else ""


def single_statement(sql: str) -> bool:
    return ";" not in sql.strip().rstrip(";")


def _sqlstate_from(message: str) -> str | None:
    """libpq reports startup refusals as text only; map the ones the labs teach."""
    return "53300" if "too many connections" in message else None


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
    # Sessions the lab opens at install: by default left inside an open transaction (a stuck job);
    # `idle: true` commits so they sit idle (a leaked connection), `count` opens several, `login_role` logs in
    # as a role the lab created (counts against that role's CONNECTION LIMIT).
    scenario_sessions: tuple[dict[str, Any], ...] = ()
    session_ttl_s: int = SESSION_TTL_S
    # lab_control "reproduce": one fresh connection the way the customer's app makes it, then closed.
    reproduce: dict[str, Any] | None = None

    @property
    def login_roles(self) -> set[str]:
        roles = {s["login_role"] for s in self.scenario_sessions if s.get("login_role")}
        if self.reproduce and self.reproduce.get("login_role"):
            roles.add(self.reproduce["login_role"])
        bad = [r for r in roles if not LAB_LOGIN_ROLE.match(r)]
        if bad:
            raise ValueError(f"lab {self.slug}: login roles must be lab-owned (labNN_name): {bad}")
        return roles

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
            scenario_sessions=tuple(spec.get("scenario_sessions", [])),
            session_ttl_s=min(int(spec.get("session_ttl_s", SESSION_TTL_S)), MAX_SESSION_TTL_S),
            reproduce=spec.get("reproduce"),
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
    pid: int = 0
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
        self.role_passwords: dict[str, str] = {}  # in memory only; reset at every install

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
        sql = unwrap_rollback(args.sql.strip())
        out: dict[str, Any] = {"ok": True, "role": args.role, "claims": args.claims,
                               "statement": statement_kind(sql), "rows": [], "truncated": False,
                               "row_count": None, "persisted": False, "database": "lab"}
        if signal := SIGNAL_OWN.fullmatch(sql):
            return await self._signal_session(signal.group(1).lower(), int(signal.group(2)), args, out, user_id)
        if reason := deny_reason(sql):
            return {"ok": False, "refused": True, "reason": reason, "role": args.role, "database": "lab"}
        if args.session:
            return await self._run_in_session(args, sql, out, user_id)

        persist_allowed = bool(self.active and out["statement"] in self.active.spec.persistent_steps)
        if args.persist and not persist_allowed:
            declared = list(self.active.spec.persistent_steps) if self.active else []
            out["persist_note"] = (f"not persisted: '{out['statement']}' is not a declared persistent step "
                                   f"(declared: {declared or 'none'}; install a lab first)")
        if out["statement"] in NO_TRANSACTION:
            return await self._run_without_transaction(args, sql, out, persist_allowed, user_id)
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

    async def _run_without_transaction(self, args: RunLabSqlInput, sql: str, out: dict[str, Any],
                                       persist_allowed: bool, user_id: UUID) -> dict[str, Any]:
        """VACUUM cannot run in a transaction block, so it can never be rolled back: declared steps only."""
        if not (args.persist and persist_allowed):
            out.update(ok=False, refused=True,
                       reason=f"{out['statement'].upper()} cannot run inside the runner's rolled-back transaction; "
                              "it is only available where the lab declares it as a persistent step "
                              "(call again with persist=true)")
            return out
        if not single_statement(sql):
            out.update(ok=False, refused=True, reason=f"{out['statement'].upper()} must be sent on its own")
            return out
        started = time.monotonic()
        async with self.pool.connection() as conn:  # autocommit; session settings are discarded on return
            try:
                await conn.execute(f"set statement_timeout = {self._timeout_ms()}")
                if args.role != "postgres":
                    await conn.execute(f"set role {args.role}")
                await self._execute(conn, sql, out)
                out["persisted"] = True
            except psycopg.Error as e:
                self._error(out, e)
        out["ms"] = round((time.monotonic() - started) * 1000, 1)
        await self._log(user_id, args, sql, out)
        return out

    async def _signal_session(self, kind: str, pid: int, args: RunLabSqlInput, out: dict[str, Any],
                              user_id: UUID) -> dict[str, Any]:
        """Real pg_terminate_backend / pg_cancel_backend, but only for a lab session this runner opened."""
        name = next((n for n, sess in self.sessions.items() if sess.pid == pid), None)
        if name is None:
            return {"ok": False, "refused": True, "database": "lab", "role": args.role,
                    "reason": f"pid {pid} is not a session this lab opened; only lab sessions can be signalled here "
                              "(other backends may belong to the tutor itself)"}
        started = time.monotonic()
        async with self.pool.connection() as conn:
            cur = conn.cursor(row_factory=dict_row)
            await cur.execute(f"select pg_{kind}_backend(%s)".encode(), (pid,))
            out["rows"] = await cur.fetchall()
            out["row_count"] = 1
        out["ms"] = round((time.monotonic() - started) * 1000, 1)
        out["signalled_session"] = name
        if kind == "terminate":
            await self._close_session(name)  # its connection is gone; drop our handle
        await self._log(user_id, args, sql=f"select pg_{kind}_backend({pid})", out=out)
        return out

    # ------------------------------------------------------------------ named sessions
    def _session_ttl_s(self) -> int:
        return self.active.spec.session_ttl_s if self.active else SESSION_TTL_S

    async def _connect_as(self, login_role: str | None, application_name: str | None = None,
                          ) -> AsyncConnection:
        kwargs: dict[str, Any] = {"application_name": application_name} if application_name else {}
        if login_role:
            kwargs |= {"user": login_role, "password": self.role_passwords[login_role]}
        return await AsyncConnection.connect(self.lab_url, autocommit=False, **kwargs)

    async def _open_session(self, name: str, application_name: str | None = None,
                            login_role: str | None = None) -> NamedSession:
        conn = await self._connect_as(login_role, application_name)
        await conn.execute(f"set statement_timeout = {self._timeout_ms()}")
        await conn.execute(f"set lock_timeout = {self._lock_timeout_ms()}")
        if application_name:
            await conn.execute("select set_config('application_name', %s, false)", (application_name,))
        row = await (await conn.execute("select pg_backend_pid()")).fetchone()
        await conn.commit()  # the settings above are session-level; start the lab transaction clean
        session = self.sessions[name] = NamedSession(conn, pid=row[0] if row else 0)
        session.expiry = asyncio.create_task(self._expire(name, session, self._session_ttl_s()))
        return session

    async def _run_in_session(self, args: RunLabSqlInput, sql: str, out: dict[str, Any],
                              user_id: UUID) -> dict[str, Any]:
        name = args.session or "a"
        session = self.sessions.get(name) or await self._open_session(name)
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
                       f"lab_control reset or {self._session_ttl_s()}s")
        await self._log(user_id, args, sql, out)
        return out

    async def _expire(self, name: str, session: NamedSession, ttl_s: int) -> None:
        await asyncio.sleep(ttl_s)
        if self.sessions.get(name) is session:
            await self._close_session(name)

    async def _close_session(self, name: str) -> None:
        session = self.sessions.pop(name, None)
        if session is None:
            return
        if session.expiry and session.expiry is not asyncio.current_task():
            session.expiry.cancel()
        try:
            if not session.conn.closed:
                await session.conn.rollback()
        except psycopg.Error:
            pass  # e.g. the backend was terminated: nothing left to roll back
        finally:
            await session.conn.close()

    async def close_sessions(self) -> None:
        for name in list(self.sessions):
            await self._close_session(name)

    # ------------------------------------------------------------------ lab_control
    async def control(self, args: LabControlInput, user_id: UUID) -> dict[str, Any]:
        handlers: dict[str, Callable[[LabSpec, UUID], Awaitable[dict[str, Any]]]] = {
            "install": self._install, "reset": self._install, "status": self._status,
            "hint": self._hint, "check": self._check, "reproduce": self._reproduce,
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
            for role in spec.login_roles:  # created NOLOGIN by setup.sql; a new random password per install
                self.role_passwords[role] = secrets.token_urlsafe(24)
                await conn.execute(sql.SQL("alter role {} login password {}").format(
                    sql.Identifier(role), sql.Literal(self.role_passwords[role])))
        self.active = ActiveLab(spec, lab_run_id=await self._start_run(spec, user_id))
        for scenario in spec.scenario_sessions:  # e.g. a job that holds locks and stays idle in transaction
            count = int(scenario.get("count", 1))
            for i in range(count):
                name = f"{scenario['name']}-{i + 1}" if count > 1 else scenario["name"]
                session = await self._open_session(name, scenario.get("application_name"), scenario.get("login_role"))
                await session.conn.execute(scenario["sql"].encode())
                if scenario.get("idle"):
                    await session.conn.commit()
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

    async def _reproduce(self, spec: LabSpec, user_id: UUID) -> dict[str, Any]:
        """Open one new connection exactly as the lab's app does, run its request, close it: real errors only."""
        if not spec.reproduce:
            return {"ok": False, "error": f"lab {spec.slug} has no reproduce step"}
        rep = spec.reproduce
        out: dict[str, Any] = {"ok": True, "reproduced_as": rep.get("login_role") or "postgres",
                               "application_name": rep.get("application_name"), "request": rep["sql"]}
        started = time.monotonic()
        try:
            conn = await self._connect_as(rep.get("login_role"), rep.get("application_name"))
        except psycopg.OperationalError as e:  # refused at connection start, e.g. 53300
            message = str(e).strip().splitlines()[-1]
            out.update(ok=False, stage="connect", sqlstate=e.sqlstate or _sqlstate_from(message), message=message)
        else:
            try:
                async with conn:
                    cur = conn.cursor(row_factory=dict_row)
                    await cur.execute(f"set statement_timeout = {self._timeout_ms()}")
                    await cur.execute(rep["sql"].encode())
                    rows = await cur.fetchall() if cur.description else []
                    out.update(stage="query", rows=rows[:MAX_ROWS], row_count=len(rows))
                    out["session_settings"] = {k: (await (await conn.execute(f"show {k}")).fetchone() or [""])[0]
                                               for k in ("idle_session_timeout", "statement_timeout")}
            except psycopg.Error as e:
                out.update(ok=False, stage="query", sqlstate=e.sqlstate, message=e.diag.message_primary)
        out["ms"] = round((time.monotonic() - started) * 1000, 1)
        return out

    async def _check(self, spec: LabSpec, user_id: UUID) -> dict[str, Any]:
        checks = (spec.path / "checks.sql").read_text(encoding="utf-8")
        lines: list[str] = []
        try:
            async with self.pool.connection() as conn:  # settings are discarded when the connection returns
                await conn.execute(f"set statement_timeout = {self._timeout_ms()}")
                await conn.execute(f"set lock_timeout = {self._lock_timeout_ms()}")
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
