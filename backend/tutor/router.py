"""FastAPI router for the tutor. Host apps mount it with `app.include_router(router, prefix="/tutor")`
and put a `TutorService` on `app.state.tutor`.

POST /session              start a session
GET  /session/{id}         session + transcript (what the learner saw)
POST /turn                 one tutor turn as Server-Sent Events:
                           token, tool_call, tool_result_summary, rewrite, turn, lab, error, incident,
                           mode (first message is a customer problem: the session starts in incident mode)
                           (`lab`: the app ran the turn's lab_action, e.g. installed lab 01)
GET  /ledger               mastery ledger, weakest first
GET  /labs                 available labs
POST /lab/{slug}/{action}  install | reset | status | hint | check for the session's lab
POST /lab/sql              the learner's own SQL in the same lab sandbox the tutor uses (lab console)
POST /internal/refresh     start a docs refresh (pg_cron via pg_net); header X-Refresh-Token; 202 / 409
GET  /internal/refresh     recent refresh runs (same token)
GET  /voice                server TTS availability and voices per language
PATCH /session/{id}/incident  the learner edits the incident model (set/clear a field, add/remove evidence)
POST /voice/speech         signed URL to the cached server audio of one tutor turn's `speech` track
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

from backend.tutor.host import HostRefusal
from backend.tutor.incident import (
    IncidentState,
    ScalarField,
    learner_edit,
    looks_like_customer_problem,
    merge,
)
from backend.tutor.orchestrator import Final, Rewrite, Token, ToolCall, ToolResultSummary
from backend.tutor.service import TutorService
from backend.tutor.tools import LabControlInput, LabRole, RunLabSqlInput, ToolContext
from backend.tutor.voice import TtsUnavailable

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
    delivery: Literal["socratic", "explicit"] = "socratic"  # hosts like AuDHS default to explicit


class TurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: UUID
    text: str = Field(min_length=1, max_length=20000)
    input_mode: Literal["text", "voice"] = "text"  # voice: final Web Speech transcript (T2.1)


class IncidentEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: ScalarField | Literal["evidence"]
    value: str | None = Field(default=None, max_length=4000)  # evidence: adds an item
    index: int | None = Field(default=None, ge=0)  # evidence without value: removes this item


class SpeechRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    turn_id: UUID  # by turn, not free text: only a turn's `speech` track is ever voiced


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    trigger: Literal["cron", "manual", "api"] = "api"


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


@router.patch("/session/{session_id}/incident")
async def edit_incident(session_id: UUID, body: IncidentEdit, svc: Svc, user: User) -> dict[str, Any]:
    session = await _session_or_404(svc, user, session_id)
    state = learner_edit(IncidentState.model_validate(session["incident"] or {}), body.field, body.value, body.index)
    await svc.store.save_incident(user, session_id, state)
    return {"incident": state.model_dump(mode="json")}


@router.get("/ledger")
async def get_ledger(svc: Svc, user: User) -> dict[str, Any]:
    return {"entries": [e.model_dump(mode="json") for e in await svc.ledger.read(user)]}


@router.get("/labs")
async def list_labs(svc: Svc, user: User) -> dict[str, Any]:
    return {"labs": [{"slug": s.slug, "phase": s.phase, "title": s.title, "requires": list(s.requires),
                      "reproducible": s.reproduce is not None}
                     for s in svc.runner(UUID(int=0)).labs.values()]}


@router.post("/lab/{slug}/{action}")
async def lab_action(slug: str, action: Literal["install", "reset", "status", "hint", "check", "reproduce"],
                     session_id: UUID, svc: Svc, user: User) -> dict[str, Any]:
    await _session_or_404(svc, user, session_id)
    return await svc.runner(session_id).control(LabControlInput(slug=slug, action=action), user)


@router.post("/lab/sql")
async def lab_sql(body: LabSql, svc: Svc, user: User) -> dict[str, Any]:
    await _session_or_404(svc, user, body.session_id)
    args = RunLabSqlInput(sql=body.sql, role=body.role, claims=body.claims, explain=body.explain,
                          persist=body.persist, session=body.session)
    return await svc.runner(body.session_id).run_sql(args, user)


def _refresh_or_401(svc: TutorService, request: Request) -> Any:
    refresh = svc.refresh
    if refresh is None or not refresh.configured:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "docs refresh not configured (TUTOR_REFRESH_TOKEN)")
    if not refresh.token_ok(request.headers.get("x-refresh-token")):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid refresh token")
    return refresh


@router.post("/internal/refresh", status_code=status.HTTP_202_ACCEPTED)
async def start_refresh(request: Request, svc: Svc, body: RefreshRequest | None = None) -> Any:
    refresh = _refresh_or_401(svc, request)
    run_id, started = await refresh.start((body or RefreshRequest()).trigger)
    if not started:
        raise HTTPException(status.HTTP_409_CONFLICT, f"a refresh is already running ({run_id})")
    return {"run_id": run_id, "started": True}


@router.get("/internal/refresh")
async def refresh_status(request: Request, svc: Svc) -> Any:
    refresh = _refresh_or_401(svc, request)
    return {"running": refresh.running, "runs": await refresh.recent()}


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
    if svc.hooks:  # the host may refuse, e.g. when its daily hosted budget is spent
        try:
            await svc.hooks.before_turn(user)
        except HostRefusal as e:
            raise HTTPException(e.status_code, e.message) from e

    async def events() -> AsyncIterator[dict[str, str]]:
        async with lock:
            history = await svc.store.history(user, body.session_id)
            if not history and session["mode"] != "incident" and looks_like_customer_problem(body.text):
                # The learner opens with a real problem: incident mode from the first turn, no onboarding (T2.2a).
                await svc.store.set_mode(user, body.session_id, "incident")
                session["mode"] = "incident"
                yield _sse("mode", {"mode": "incident", "reason": "customer_problem"})
            state = await svc.session_state(user, session, history)
            runner = svc.runner(body.session_id)
            ctx = ToolContext(user_id=user, retriever=svc.retriever, ledger=svc.ledger, lab=runner, web=svc.web,
                              web_enabled=svc.web is not None, learner_text=body.text)
            before = runner.active.lab_run_id if runner.active else None  # detects lab_control installs
            try:
                async for event in svc.orchestrator(user).run_turn(history=history, user_text=body.text, state=state,
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
                                                         event.usage, previous_mode=session["mode"],
                                                         input_mode=body.input_mode)
                        yield _sse("turn", {"turn_id": turn_id, "turn": event.turn.model_dump(mode="json"),
                                            "usage": event.usage, "model": event.model,
                                            "findings": [f.model_dump() for f in event.findings]})
                        if event.turn.session_end:  # the five end-of-session headings, kept for the next session
                            await svc.store.end_session(user, body.session_id,
                                                        event.turn.session_end.model_dump(mode="json"))
                        if event.turn.incident:  # merge the partial update into the session's incident model
                            current = IncidentState.model_validate(session["incident"] or {})
                            merged, changed = merge(current, event.turn.incident)
                            await svc.store.save_incident(user, body.session_id, merged)
                            yield _sse("incident", {"incident": merged.model_dump(mode="json"), "changed": changed})
                        installed = runner.active if runner.active and runner.active.lab_run_id != before else None
                        action = event.turn.lab_action
                        if action and not (installed and action.action == "install"
                                           and action.slug == installed.spec.slug):
                            result = await runner.control(LabControlInput(slug=action.slug, action=action.action), user)
                            yield _sse("lab", {"slug": action.slug, "action": action.action, "result": result})
                        elif installed:  # the model installed a lab via lab_control during the turn
                            status_ = await runner.control(LabControlInput(slug=installed.spec.slug, action="status"),
                                                           user)
                            status_.pop("coaching_for_tutor_only", None)  # the learner's UI must not get the answers
                            yield _sse("lab", {"slug": installed.spec.slug, "action": "install", "result": status_})
            except anthropic.APIStatusError as e:
                yield _sse("error", {"status": e.status_code, "message": e.message})
            except anthropic.APIConnectionError:
                yield _sse("error", {"status": 502, "message": "could not reach the Anthropic API"})

    return EventSourceResponse(events())


@router.get("/voice")
async def voice_info(svc: Svc, user: User) -> dict[str, Any]:
    if svc.voice is None:
        return {"tts": "browser", "voices": {}}
    return {"tts": "server", "voices": svc.voice.voices()}


@router.post("/voice/speech")
async def voice_speech(body: SpeechRequest, svc: Svc, user: User) -> dict[str, Any]:
    if svc.voice is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "server TTS is off (TUTOR_TTS=browser)")
    found = await svc.store.speech(user, body.turn_id)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "turn not found")
    try:
        return await svc.voice.speech_url(*found)
    except TtsUnavailable as e:  # the browser falls back to Web Speech
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
