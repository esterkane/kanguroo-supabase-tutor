"""TutorService: everything the router needs, built once per app (ADR-009: no host-app imports).

Conversation storage is append-only: `TurnStore.append` writes each API message verbatim into
tutor.turn.message (ordered by seq) and `history` returns them unchanged. All user data is read and
written as the learner (`as_user`), so RLS decides access.
"""
from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from anthropic import AsyncAnthropic
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from backend.tutor.auth import JwtVerifier
from backend.tutor.db import as_user
from backend.tutor.host import HostHooks, ModelCall, Verifier
from backend.tutor.incident import IncidentState
from backend.tutor.lab_runner import LabRunner, lab_pool
from backend.tutor.ledger import LedgerStore, PgLedger
from backend.tutor.orchestrator import Message, Orchestrator, reply_text
from backend.tutor.prompt import ONBOARDING_LAB, ActiveLab, OnboardingStep, SessionState
from backend.tutor.refresh import RefreshManager
from backend.tutor.retrieval import PgHybridRetriever, Retriever, embedder_from_env
from backend.tutor.review import due_topics
from backend.tutor.schemas import TutorTurn
from backend.tutor.voice import VoiceService
from backend.tutor.web import BraveSearch, TavilySearch, web_from_env

APP_MESSAGE = "[app message, not from the learner]"


def _row_for(message: Message) -> tuple[str, str]:
    """(tutor.turn.role, display content) for one API message."""
    role, content = message["role"], message["content"]
    if role == "system":
        return "system", str(content).splitlines()[0] if content else ""
    if role == "assistant":
        return "assistant", reply_text(content if isinstance(content, list) else [])
    if isinstance(content, list):  # tool results go back to the model as a user message
        return "tool", f"{len(content)} tool result(s)"
    return "user", str(content)


@dataclass
class TurnStore:
    pool: AsyncConnectionPool

    async def create_session(self, user_id: UUID, *, objective: str | None, mode: str, language: str,
                             persona_on: bool, delivery: str = "socratic") -> dict[str, Any]:
        async with as_user(self.pool, user_id) as conn:
            cur = conn.cursor(row_factory=dict_row)
            await cur.execute(
                "insert into tutor.session (objective, mode, language, persona_on, delivery)"
                " values (%s, %s, %s, %s, %s) returning id, objective, mode, language, persona_on, delivery, started_at",
                (objective, mode, language, persona_on, delivery))
            row = await cur.fetchone()
            assert row is not None
            return row

    async def session(self, user_id: UUID, session_id: UUID) -> dict[str, Any] | None:
        async with as_user(self.pool, user_id) as conn:
            cur = conn.cursor(row_factory=dict_row)
            await cur.execute("select id, objective, mode, language, persona_on, delivery, started_at, ended_at, incident "
                              "from tutor.session where id = %s", (session_id,))
            return await cur.fetchone()

    async def end_session(self, user_id: UUID, session_id: UUID, summary: dict[str, Any]) -> None:
        """Store the session-end block; a later `recap` in the same session replaces it."""
        async with as_user(self.pool, user_id) as conn:
            await conn.execute("update tutor.session set summary = %s::jsonb, ended_at = now() where id = %s",
                               (json.dumps(summary), session_id))

    async def last_summary(self, user_id: UUID, current: UUID) -> dict[str, Any] | None:
        """The summary of the learner's most recently ended other session."""
        async with as_user(self.pool, user_id) as conn:
            cur = await conn.execute("select summary from tutor.session where summary is not null and id <> %s "
                                     "order by ended_at desc limit 1", (current,))
            row = await cur.fetchone()
        return row[0] if row else None

    async def set_mode(self, user_id: UUID, session_id: UUID, mode: str) -> None:
        async with as_user(self.pool, user_id) as conn:
            await conn.execute("update tutor.session set mode = %s where id = %s", (mode, session_id))

    async def save_incident(self, user_id: UUID, session_id: UUID, state: IncidentState) -> None:
        async with as_user(self.pool, user_id) as conn:
            await conn.execute("update tutor.session set incident = %s::jsonb where id = %s",
                               (state.model_dump_json(), session_id))

    async def history(self, user_id: UUID, session_id: UUID) -> list[Message]:
        async with as_user(self.pool, user_id) as conn:
            cur = await conn.execute("select message from tutor.turn where session_id = %s and message is not null "
                                     "order by seq", (session_id,))
            return [row[0] for row in await cur.fetchall()]

    async def transcript(self, user_id: UUID, session_id: UUID) -> list[dict[str, Any]]:
        """What the learner saw: their messages and the tutor's turns (no system/tool/app rows)."""
        async with as_user(self.pool, user_id) as conn:
            cur = conn.cursor(row_factory=dict_row)
            await cur.execute(
                "select id, role, content, tutor_turn, created_at from tutor.turn where session_id = %s "
                "and (role = 'user' and content not like %s or role = 'assistant' and tutor_turn is not null) "
                "order by seq", (session_id, APP_MESSAGE + "%"))
            return await cur.fetchall()

    async def onboarding_step(self, user_id: UUID, session_id: UUID) -> OnboardingStep | None:
        """Where the learner is on the first-session path; None once lab 01 was ever handed over to them, or once
        this session worked an incident (the learner came with a real problem, T2.2a)."""
        async with as_user(self.pool, user_id) as conn:
            cur = await conn.execute(
                "select exists (select 1 from tutor.lab_run where lab_slug = %s),"
                "       count(*) filter (where tutor_turn is not null),"
                "       bool_or(tutor_turn->'diagrams' @> '[{\"kind\": \"sequenceDiagram\"}]'),"
                "       coalesce(bool_or(tutor_turn->>'mode' = 'incident'), false)"
                " from tutor.turn where session_id = %s", (ONBOARDING_LAB, session_id))
            handed_over, tutor_turns, has_flow_diagram, had_incident = await cur.fetchone() or (False, 0, False, False)
        if handed_over or had_incident:
            return None
        if not tutor_turns:
            return "opening"
        return "lab_handover" if has_flow_diagram else "request_flow"

    async def speech(self, user_id: UUID, turn_id: UUID) -> tuple[str, str] | None:
        """(speech, language) of one of the learner's own tutor turns; RLS hides everyone else's."""
        async with as_user(self.pool, user_id) as conn:
            cur = await conn.execute("select tutor_turn->>'speech', tutor_turn->>'language' from tutor.turn "
                                     "where id = %s and role = 'assistant' and tutor_turn is not null", (turn_id,))
            row = await cur.fetchone()
        return (row[0] or "", row[1] or "de") if row else None

    async def append(self, user_id: UUID, session_id: UUID, messages: list[Message], turn: TutorTurn,
                     usage: dict[str, int], previous_mode: str, input_mode: str = "text") -> UUID:
        """Persist one turn's messages verbatim; the TutorTurn goes on the last assistant message.

        input_mode marks how the learner's message (the first one) was entered; tool results stay 'text'."""
        last_assistant = max(i for i, m in enumerate(messages) if m["role"] == "assistant")
        turn_id: UUID | None = None
        async with as_user(self.pool, user_id) as conn:
            for i, message in enumerate(messages):
                role, content = _row_for(message)
                final = i == last_assistant
                cur = await conn.execute(
                    "insert into tutor.turn (session_id, role, content, message, tutor_turn, input_tokens,"
                    " output_tokens, input_mode) values (%s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s) returning id",
                    (session_id, role, turn.text if final else content, json.dumps(message),
                     turn.model_dump_json() if final else None,
                     usage.get("input_tokens") if final else None, usage.get("output_tokens") if final else None,
                     input_mode if i == 0 and role == "user" else "text"))
                row = await cur.fetchone()
                if final and row:
                    turn_id = row[0]
            assert turn_id is not None
            for c in turn.citations:
                await conn.execute(
                    "insert into tutor.citation (turn_id, n, url, title, tier, fetched_at) "
                    "values (%s, %s, %s, %s, %s, %s::timestamptz)",
                    (turn_id, c.n, c.url, c.title, c.tier, c.fetched_at))
            if turn.mode != previous_mode:  # the learner switched mode ("neutral", "exam", ...)
                await conn.execute("update tutor.session set mode = %s where id = %s", (turn.mode, session_id))
        return turn_id


@dataclass
class TutorService:
    app_pool: AsyncConnectionPool
    lab_pool: AsyncConnectionPool
    lab_url: str
    verifier: Verifier  # JwtVerifier standalone, HostVerifier when mounted in a host
    retriever: Retriever
    ledger: LedgerStore
    anthropic: AsyncAnthropic | None
    refresh: RefreshManager | None = None
    voice: VoiceService | None = None  # server TTS (TUTOR_TTS=server); None: browser voices only
    web: BraveSearch | TavilySearch | None = None  # web_search provider (TUTOR_WEB_SEARCH=on + key)
    hooks: HostHooks | None = None  # host app: may refuse a turn, receives every model call
    store: TurnStore = field(init=False)
    runners: dict[UUID, LabRunner] = field(default_factory=dict)
    locks: dict[UUID, asyncio.Lock] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.store = TurnStore(self.app_pool)

    @classmethod
    def from_env(cls) -> TutorService:
        db_url = os.environ.get("SUPABASE_DB_URL") or os.environ["DB_URL"]
        lab_url = os.environ.get("LAB_DB_URL") or db_url.rsplit("/", 1)[0] + "/lab"
        app_pool = AsyncConnectionPool(db_url, min_size=1, max_size=8, open=False)
        has_llm = bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
        return cls(
            app_pool=app_pool, lab_pool=lab_pool(lab_url, min_size=1, max_size=4), lab_url=lab_url,
            verifier=JwtVerifier(os.environ["API_URL"]),
            retriever=PgHybridRetriever(app_pool, embedder_from_env()), ledger=PgLedger(app_pool),
            anthropic=AsyncAnthropic() if has_llm else None,
            refresh=RefreshManager(app_pool, db_url, os.environ.get("TUTOR_REFRESH_TOKEN")),
            voice=VoiceService.from_env(),
            web=web_from_env(),
        )

    async def open(self) -> None:
        await self.app_pool.open()
        await self.lab_pool.open()

    async def close(self) -> None:
        if self.refresh:
            await self.refresh.close()
        if self.voice:
            await self.voice.close()
        if self.web:
            await self.web.client.aclose()
        for runner in self.runners.values():
            await runner.close_sessions()
        await self.lab_pool.close()
        await self.app_pool.close()

    def runner(self, session_id: UUID) -> LabRunner:
        """One lab runner per tutor session (in-process: active lab, hints and named sessions live here)."""
        if session_id not in self.runners:
            self.runners[session_id] = LabRunner(self.lab_pool, self.lab_url, app_pool=self.app_pool,
                                                 session_id=session_id)
        return self.runners[session_id]

    def lock(self, session_id: UUID) -> asyncio.Lock:
        return self.locks.setdefault(session_id, asyncio.Lock())

    def orchestrator(self, user_id: UUID | None = None) -> Orchestrator:
        assert self.anthropic is not None
        hooks = self.hooks
        if hooks is None or user_id is None:
            return Orchestrator(client=self.anthropic)

        async def report(call: ModelCall) -> None:
            await hooks.on_model_call(user_id, call)
        return Orchestrator(client=self.anthropic, on_call=report)

    async def session_state(self, user_id: UUID, session: dict[str, Any], history: list[Message]) -> SessionState:
        ledger = await self.ledger.read(user_id)
        runner = self.runners.get(session["id"])
        lab = runner.active if runner else None
        incident_mode = session["mode"] == "incident"
        onboarding = None if incident_mode else await self.store.onboarding_step(user_id, session["id"])
        last = await self.store.last_summary(user_id, session["id"]) or {}
        return SessionState(
            mode=session["mode"], language=session["language"], persona_on=session["persona_on"],
            delivery=session.get("delivery", "socratic"),
            objective=session["objective"], ledger=ledger,
            active_lab=ActiveLab(lab.spec.slug, lab.spec.title, lab.hints_used) if lab else None,
            first_turn=not history and not ledger and not incident_mode,
            onboarding=onboarding,
            incident=IncidentState.model_validate(session["incident"]) if session.get("incident") else None,
            due=due_topics(ledger),
            still_wrong=tuple(last.get("still_wrong", [])),
            retrieval_questions=tuple(last.get("retrieval_questions", [])),
        )
