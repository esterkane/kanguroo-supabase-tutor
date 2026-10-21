"""FastAPI router for the tutor. Host apps mount it with `app.include_router(router, prefix="/tutor")`
and put a `TutorService` on `app.state.tutor`.

POST /session              start a session
GET  /session/{id}         session + transcript (what the learner saw)
POST /turn                 one tutor turn as Server-Sent Events:
                           token, tool_call, tool_result_summary, rewrite, turn, error
GET  /ledger               mastery ledger, weakest first
GET  /labs                 available labs
POST /lab/{slug}/{action}  install | reset | status | hint | check for the session's lab
POST /lab/sql              the learner's own SQL in the same lab sandbox the tutor uses (lab console)
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import asdict
from typing import Annotated, Any, Literal
from uuid import UUID

import anthropic
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sse_starlette import EventSourceResponse

from backend.tutor.orchestrator import Final, Rewrite, Token, ToolCall, ToolResultSummary
from backend.tutor.service import TutorService
from backend.tutor.tools import LabControlInput, LabRole, RunLabSqlInput, ToolContext

router = APIRouter(tags=["tutor"])


def service(request: Request) -> TutorService:
    svc: TutorService | None = getattr(request.app.state, "tutor", None)
    if svc is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "tutor service not configured")
    return svc


async def current_user(request: Request, svc: Annotated[TutorService, Depends(service)]) -> UUID:
    return await svc.verifier.user_id(request)


Svc = Annotated[TutorService, Depends(service)]
User = Annotated[UUID, Depends(current_user)]


class NewSession(BaseModel):
    model_config = ConfigDict(extra="forbid")
    objective: str | None = Field(default=None, max_length=500)
    mode: Literal["lesson", "incident", "exam", "neutral", "rabbit_hole"] = "lesson"
    language: Literal["de", "en"] = "de"
    persona_on: bool = True


class TurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: UUID
    text: str = Field(min_length=1, max_length=20000)


class LabSql(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: UUID
    sql: str = Field(min_length=1, max_length=20000)
    role: LabRole = "authenticated"
    claims: dict[str, Any] | None = None
    explain: bool = False
    persist: bool = False  # honoured only for steps the active lab declares persistent
    session: str | None = Field(default=None, max_length=20)


async def _session_or_404(svc: TutorService, user: UUID, session_id: UUID) -> dict[str, Any]:
    session = await svc.store.session(user, session_id)
    if session is None:  # RLS hides other learners' sessions, so "not yours" looks like "not found"
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    return session


@router.post("/session", status_code=status.HTTP_201_CREATED)
async def create_session(body: NewSession, svc: Svc, user: User) -> dict[str, Any]:
    return await svc.store.create_session(user, **body.model_dump())


@router.get("/session/{session_id}")
async def get_session(session_id: UUID, svc: Svc, user: User) -> dict[str, Any]:
    session = await _session_or_404(svc, user, session_id)
    return {**session, "transcript": await svc.store.transcript(user, session_id)}


@router.get("/ledger")
async def get_ledger(svc: Svc, user: User) -> dict[str, Any]:
    return {"entries": [e.model_dump(mode="json") for e in await svc.ledger.read(user)]}


@router.get("/labs")
async def list_labs(svc: Svc, user: User) -> dict[str, Any]:
    return {"labs": [{"slug": s.slug, "phase": s.phase, "title": s.title, "requires": list(s.requires)}
                     for s in svc.runner(UUID(int=0)).labs.values()]}


@router.post("/lab/{slug}/{action}")
async def lab_action(slug: str, action: Literal["install", "reset", "status", "hint", "check"], session_id: UUID,
                     svc: Svc, user: User) -> dict[str, Any]:
    await _session_or_404(svc, user, session_id)
    return await svc.runner(session_id).control(LabControlInput(slug=slug, action=action), user)


@router.post("/lab/sql")
async def lab_sql(body: LabSql, svc: Svc, user: User) -> dict[str, Any]:
    await _session_or_404(svc, user, body.session_id)
    args = RunLabSqlInput(sql=body.sql, role=body.role, claims=body.claims, explain=body.explain,
                          persist=body.persist, session=body.session)
    return await svc.runner(body.session_id).run_sql(args, user)


def _sse(event: str, data: Any) -> dict[str, str]:
    return {"event": event, "data": json.dumps(data, ensure_ascii=False, default=str)}


@router.post("/turn")
async def turn(body: TurnRequest, svc: Svc, user: User) -> EventSourceResponse:
    if svc.anthropic is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "no Anthropic credentials: set ANTHROPIC_API_KEY in .env and restart the backend")
    session = await _session_or_404(svc, user, body.session_id)
    lock = svc.lock(body.session_id)
    if lock.locked():
        raise HTTPException(status.HTTP_409_CONFLICT, "a turn is already running for this session")

    async def events() -> AsyncIterator[dict[str, str]]:
        async with lock:
            history = await svc.store.history(user, body.session_id)
            state = await svc.session_state(user, session, history)
            ctx = ToolContext(user_id=user, retriever=svc.retriever, ledger=svc.ledger,
                              lab=svc.runner(body.session_id))
            try:
                async for event in svc.orchestrator().run_turn(history=history, user_text=body.text, state=state,
                                                               ctx=ctx):
                    if isinstance(event, Token):
                        yield _sse("token", {"text": event.text})
                    elif isinstance(event, ToolCall):
                        yield _sse("tool_call", asdict(event))
                    elif isinstance(event, ToolResultSummary):
                        yield _sse("tool_result_summary", asdict(event))
                    elif isinstance(event, Rewrite):
                        yield _sse("rewrite", asdict(event))
                    elif isinstance(event, Final):
                        # Persist only complete turns, so the stored history stays replayable.
                        turn_id = await svc.store.append(user, body.session_id, event.new_messages, event.turn,
                                                         event.usage, previous_mode=session["mode"])
                        yield _sse("turn", {"turn_id": turn_id, "turn": event.turn.model_dump(mode="json"),
                                            "usage": event.usage, "model": event.model,
                                            "findings": [f.model_dump() for f in event.findings]})
            except anthropic.APIStatusError as e:
                yield _sse("error", {"status": e.status_code, "message": e.message})
            except anthropic.APIConnectionError:
                yield _sse("error", {"status": 502, "message": "could not reach the Anthropic API"})

    return EventSourceResponse(events())
