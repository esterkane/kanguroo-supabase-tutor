"""Router: JWT verification and the HTTP/SSE flow against the local DB with a scripted Claude client."""
from __future__ import annotations

import json
import re
import time
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlparse, urlunparse
from uuid import UUID, uuid4

import httpx
import jwt
import psycopg
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI
from psycopg_pool import AsyncConnectionPool

from backend.tests.test_orchestrator import FakeClient, text_reply
from backend.tutor.auth import JwtVerifier
from backend.tutor.lab_runner import lab_pool
from backend.tutor.ledger import PgLedger
from backend.tutor.router import router
from backend.tutor.service import TutorService

API_URL = "http://127.0.0.1:54321"
KEY = ec.generate_private_key(ec.SECP256R1())
OTHER_KEY = ec.generate_private_key(ec.SECP256R1())


def token(sub: UUID | str, *, key: Any = KEY, alg: str = "ES256", **over: Any) -> str:
    claims = {"sub": str(sub), "role": "authenticated", "aud": "authenticated", "iss": f"{API_URL}/auth/v1",
              "exp": int(time.time()) + 600} | over
    return jwt.encode(claims, key, algorithm=alg, headers={"kid": "test"})


def verifier() -> JwtVerifier:
    return JwtVerifier(API_URL, key_resolver=lambda _t: KEY.public_key())


# ----------------------------------------------------------------------------- auth
def test_valid_token_verifies() -> None:
    user = uuid4()
    assert verifier().verify(token(user))["sub"] == str(user)


@pytest.mark.parametrize("bad", [
    token(uuid4(), exp=int(time.time()) - 10),
    token(uuid4(), aud="anon"),
    token(uuid4(), iss="https://evil.test/auth/v1"),
    token(uuid4(), key=OTHER_KEY),
    jwt.encode({"sub": str(uuid4()), "role": "authenticated", "aud": "authenticated",
                "iss": f"{API_URL}/auth/v1", "exp": int(time.time()) + 600}, "super-secret-jwt-key-32-bytes!!!",
               algorithm="HS256"),
])
def test_bad_tokens_are_rejected(bad: str) -> None:
    with pytest.raises(jwt.PyJWTError):
        verifier().verify(bad)


# ----------------------------------------------------------------------------- HTTP + SSE
def parse_sse(text: str) -> list[tuple[str, Any]]:
    events = []
    for block in re.split(r"\r?\n\r?\n", text.strip()):
        name = re.search(r"^event: (.*)$", block, re.MULTILINE)
        data = re.search(r"^data: (.*)$", block, re.MULTILINE)
        if name and data:
            events.append((name.group(1).strip(), json.loads(data.group(1))))
    return events


@pytest.fixture
async def api(db_url: str) -> AsyncIterator[tuple[httpx.AsyncClient, TutorService, FakeClient]]:
    lab_url = urlunparse(urlparse(db_url)._replace(path="/lab"))
    app_pool = AsyncConnectionPool(db_url, min_size=1, max_size=4, open=False)
    fake = FakeClient([])
    svc = TutorService(app_pool=app_pool, lab_pool=lab_pool(lab_url, min_size=1, max_size=2), lab_url=lab_url,
                       verifier=verifier(), retriever=None, ledger=PgLedger(app_pool),  # type: ignore[arg-type]
                       anthropic=fake)  # type: ignore[arg-type]
    await svc.open()
    app = FastAPI()
    app.include_router(router, prefix="/tutor")
    app.state.tutor = svc
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client, svc, fake
    await svc.close()


@pytest.fixture
def users(db_url: str) -> Any:
    a, b = uuid4(), uuid4()
    yield a, b
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute("delete from tutor.session where user_id = any(%s)", ([a, b],))


def auth(user: UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {token(user)}"}


async def test_requests_need_a_learner_token(api: Any) -> None:
    client, _, _ = api
    assert (await client.get("/tutor/ledger")).status_code == 401
    assert (await client.get("/tutor/ledger", headers={"Authorization": "Bearer nope"})).status_code == 401


async def test_session_turns_are_persisted_and_replayed_verbatim(api: Any, users: tuple[UUID, UUID]) -> None:
    client, svc, fake = api
    a, b = users
    created = await client.post("/tutor/session", json={"objective": "GRANT vs RLS"}, headers=auth(a))
    assert created.status_code == 201
    sid = created.json()["id"]

    fake.script += [text_reply("Kleinkünstler, GRANT ist der Haustürschlüssel."), text_reply("Zweite Antwort.")]
    first = await client.post("/tutor/turn", json={"session_id": sid, "text": "Hallo"}, headers=auth(a))
    events = parse_sse(first.text)
    names = [e for e, _ in events]
    assert names[0] == "token" and names[-1] == "turn"
    final = events[-1][1]
    assert final["turn"]["text"].startswith("Kleinkünstler") and final["turn"]["guard_flags"] == []

    stored = await svc.store.history(a, UUID(sid))
    assert [m["role"] for m in stored] == ["user", "system", "assistant"]
    assert "follow the FIRST TURN section" in stored[1]["content"]  # first turn of a new learner

    await client.post("/tutor/turn", json={"session_id": sid, "text": "Weiter", "input_mode": "voice"},
                      headers=auth(a))
    async with svc.store.pool.connection() as conn:
        cur = await conn.execute("select content, input_mode from tutor.turn where session_id = %s and role = 'user' "
                                 "order by seq", (sid,))
        assert await cur.fetchall() == [("Hallo", "text"), ("Weiter", "voice")]
    second_request = fake.requests[1]["messages"]
    assert second_request[:3] == stored  # replayed byte-identical from the database
    assert "FIRST TURN" not in second_request[4]["content"]

    view = (await client.get(f"/tutor/session/{sid}", headers=auth(a))).json()
    assert [(t["role"], t["content"][:6]) for t in view["transcript"]] == [
        ("user", "Hallo"), ("assistant", "Kleink"), ("user", "Weiter"), ("assistant", "Zweite")]
    assert view["transcript"][1]["tutor_turn"]["next_question"]

    assert (await client.get(f"/tutor/session/{sid}", headers=auth(b))).status_code == 404
    assert (await client.post("/tutor/turn", json={"session_id": sid, "text": "x"}, headers=auth(b))).status_code == 404


async def test_turn_without_credentials_is_503(api: Any, users: tuple[UUID, UUID]) -> None:
    client, svc, _ = api
    sid = (await client.post("/tutor/session", json={}, headers=auth(users[0]))).json()["id"]
    svc.anthropic = None
    res = await client.post("/tutor/turn", json={"session_id": sid, "text": "Hallo"}, headers=auth(users[0]))
    assert res.status_code == 503 and "ANTHROPIC_API_KEY" in res.json()["detail"]


async def test_lab_endpoints_use_the_sessions_runner(api: Any, users: tuple[UUID, UUID]) -> None:
    client, svc, _ = api
    a, _ = users
    sid = (await client.post("/tutor/session", json={}, headers=auth(a))).json()["id"]
    labs = (await client.get("/tutor/labs", headers=auth(a))).json()["labs"]
    assert "01-rls-vs-grant" in [lab["slug"] for lab in labs]
    installed = await client.post(f"/tutor/lab/01-rls-vs-grant/install?session_id={sid}", headers=auth(a))
    assert installed.json()["ok"] and "Customer report" in installed.json()["scenario"]
    status_ = (await client.post(f"/tutor/lab/01-rls-vs-grant/status?session_id={sid}", headers=auth(a))).json()
    assert status_["hints_total"] == 5
    state = await svc.session_state(a, await svc.store.session(a, UUID(sid)), [])
    assert state.active_lab is not None and state.active_lab.slug == "01-rls-vs-grant"
    assert (await client.get("/tutor/ledger", headers=auth(a))).json() == {"entries": []}


async def test_lab_console_runs_in_the_sessions_sandbox(api: Any, users: tuple[UUID, UUID]) -> None:
    client, _, _ = api
    a, b = users
    sid = (await client.post("/tutor/session", json={}, headers=auth(a))).json()["id"]
    await client.post(f"/tutor/lab/01-rls-vs-grant/install?session_id={sid}", headers=auth(a))
    body = {"session_id": sid, "sql": "select * from lab01.orders",
            "claims": {"sub": "11111111-1111-1111-1111-111111111111", "role": "authenticated"}}
    res = (await client.post("/tutor/lab/sql", json=body, headers=auth(a))).json()
    assert res["sqlstate"] == "42501" and res["database"] == "lab"
    refused = (await client.post("/tutor/lab/sql", json={**body, "sql": "drop database lab"}, headers=auth(a))).json()
    assert refused["refused"] is True
    assert (await client.post("/tutor/lab/sql", json=body, headers=auth(b))).status_code == 404


async def test_onboarding_opening_request_flow_lab_handover(api: Any, users: tuple[UUID, UUID]) -> None:
    client, svc, fake = api
    a, _ = users
    sid = (await client.post("/tutor/session", json={}, headers=auth(a))).json()["id"]
    flow = {"id": "d1", "kind": "sequenceDiagram", "title": "Request flow",
            "code": "sequenceDiagram\n  participant C as client\n  C->>API: GET /rest/v1/notes"}
    base = {"mode": "lesson", "language": "de", "persona_on": True, "speech": "Welche Kontrolle?",
            "next_question": "Welche Kontrolle?"}
    fake.script += [
        text_reply("Hallo Kleinkünstler, ein kleiner Fall."),
        text_reply("Erst GRANT, dann RLS.", turn={**base, "diagrams": [flow]}),
        text_reply("Hier ist dein erster Fall.", turn={**base, "lab_action": {"slug": "01-rls-vs-grant",
                                                                             "action": "install"}}),
        text_reply("Gut, dann schauen wir auf die Evidenz."),
    ]

    def step_line(request: int) -> str:
        system = [m["content"] for m in fake.requests[request]["messages"] if m["role"] == "system"][-1]
        return next((ln for ln in system.splitlines() if "Onboarding" in ln), "")

    await client.post("/tutor/turn", json={"session_id": sid, "text": "Hallo"}, headers=auth(a))
    assert "step 1 of 3 (opening)" in step_line(0)
    await client.post("/tutor/turn", json={"session_id": sid, "text": "GRANT"}, headers=auth(a))
    assert "step 2 of 3 (request-flow lesson)" in step_line(1)
    third = await client.post("/tutor/turn", json={"session_id": sid, "text": "Klar"}, headers=auth(a))
    assert "step 3 of 3 (lab handover)" in step_line(2)
    lab = [data for name, data in parse_sse(third.text) if name == "lab"]
    assert lab and lab[0]["slug"] == "01-rls-vs-grant" and lab[0]["result"]["ok"] is True
    assert "Customer report" in lab[0]["result"]["scenario"]
    assert svc.runners[UUID(sid)].active is not None

    await client.post("/tutor/turn", json={"session_id": sid, "text": "Ok"}, headers=auth(a))
    assert step_line(3) == ""  # lab 01 was handed over: onboarding is finished for this learner
    assert await svc.store.onboarding_step(a, UUID(sid)) is None


async def test_tool_installed_lab_reaches_the_ui_without_coaching(api: Any, users: tuple[UUID, UUID]) -> None:
    from backend.tests.test_orchestrator import FakeStream, message
    client, svc, fake = api
    a, _ = users
    sid = (await client.post("/tutor/session", json={}, headers=auth(a))).json()["id"]
    install = FakeStream([], message([{"type": "tool_use", "id": "toolu_lab", "name": "lab_control",
                                       "input": {"slug": "01-rls-vs-grant", "action": "install"}}], stop="tool_use"))
    lab_action = {"mode": "lesson", "language": "de", "persona_on": True, "speech": "Los?", "next_question": "Los?",
                  "lab_action": {"slug": "01-rls-vs-grant", "action": "install"}}
    fake.script += [install, text_reply("Ein Kunde meldet 42501 auf orders.", turn=lab_action)]
    res = await client.post("/tutor/turn", json={"session_id": sid, "text": "Klar"}, headers=auth(a))
    events = parse_sse(res.text)
    tool_result = fake.requests[1]["messages"][-1]["content"][0]["content"]
    assert "permission denied for table orders" in tool_result  # the model saw the real report before writing
    labs = [data for name, data in events if name == "lab"]
    assert len(labs) == 1  # lab_action install for the same lab is not run a second time
    assert labs[0]["slug"] == "01-rls-vs-grant" and "Customer report" in labs[0]["result"]["scenario"]
    assert "coaching_for_tutor_only" not in labs[0]["result"]
    runs = svc.runners[UUID(sid)].active
    assert runs is not None and runs.spec.slug == "01-rls-vs-grant"


class FakeVoice:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def voices(self) -> dict[str, str | None]:
        return {"de": "de_DE-thorsten-high", "en": None}

    async def speech_url(self, text: str, lang: str) -> dict[str, Any]:
        self.calls.append((text, lang))
        return {"url": "http://127.0.0.1:54321/storage/v1/object/sign/tutor-audio/x.mp3?token=t",
                "voice": "de_DE-thorsten-high", "cached": False}

    async def close(self) -> None:
        pass


async def test_voice_speaks_only_the_learners_own_turns_speech(api: Any, users: tuple[UUID, UUID]) -> None:
    client, svc, fake = api
    a, b = users
    assert (await client.get("/tutor/voice", headers=auth(a))).json() == {"tts": "browser", "voices": {}}
    sid = (await client.post("/tutor/session", json={}, headers=auth(a))).json()["id"]
    fake.script += [text_reply("Gut, dann schauen wir auf die Evidenz.")]
    turn_id = parse_sse((await client.post("/tutor/turn", json={"session_id": sid, "text": "Hallo"},
                                           headers=auth(a))).text)[-1][1]["turn_id"]
    off = await client.post("/tutor/voice/speech", json={"turn_id": turn_id}, headers=auth(a))
    assert off.status_code == 503

    svc.voice = FakeVoice()
    assert (await client.get("/tutor/voice", headers=auth(a))).json()["voices"]["de"] == "de_DE-thorsten-high"
    res = await client.post("/tutor/voice/speech", json={"turn_id": turn_id}, headers=auth(a))
    assert res.status_code == 200 and "/object/sign/tutor-audio/" in res.json()["url"]
    stored = await svc.store.speech(a, UUID(turn_id))
    assert stored is not None and svc.voice.calls == [stored]
    assert (await client.post("/tutor/voice/speech", json={"turn_id": turn_id}, headers=auth(b))).status_code == 404
    assert (await client.post("/tutor/voice/speech", json={"text": "beliebig"}, headers=auth(a))).status_code == 422


async def test_incident_model_is_merged_across_turns_and_editable(api: Any, users: tuple[UUID, UUID]) -> None:
    client, _svc, fake = api
    a, b = users
    sid = (await client.post("/tutor/session", json={"mode": "incident"}, headers=auth(a))).json()["id"]
    q1, q2 = "Seit wann genau ist es langsam?", "Was zeigt pg_stat_activity?"
    base = {"mode": "incident", "language": "de", "persona_on": True}
    fake.script += [
        text_reply("Erst die Fakten.", turn=base | {"speech": q1, "next_question": q1, "incident": {
            "symptom": "API langsam", "evidence": ["CPU 91%"]}}),
        text_reply("Gut, weiter.", turn=base | {"speech": q2, "next_question": q2, "incident": {
            "timeline": "seit gestern 14:00", "evidence": ["CPU 91%", "85/200 Verbindungen"],
            "hypotheses": [{"h": "fehlender Index", "rank": 1, "test": "EXPLAIN ANALYZE"}]}}),
    ]
    first = parse_sse((await client.post("/tutor/turn", json={"session_id": sid, "text": "Supabase ist langsam"},
                                         headers=auth(a))).text)
    inc = dict(first)["incident"]
    assert inc["changed"] == ["symptom", "evidence"] and inc["incident"]["model"]["symptom"] == "API langsam"

    edited = await client.patch(f"/tutor/session/{sid}/incident", json={"field": "scope", "value": "nur Org A"},
                                headers=auth(a))
    assert edited.status_code == 200 and edited.json()["incident"]["sources"]["scope"] == "learner"

    second = parse_sse((await client.post("/tutor/turn", json={"session_id": sid, "text": "Seit gestern"},
                                          headers=auth(a))).text)
    model = dict(second)["incident"]["incident"]["model"]
    assert model["symptom"] == "API langsam" and model["scope"] == "nur Org A"
    assert model["evidence"] == ["CPU 91%", "85/200 Verbindungen"]
    state_msg = next(m["content"] for m in reversed(fake.requests[1]["messages"])  # the model saw the merged
                     if m["role"] == "system")                                         # model and the learner edit
    assert "- SYMPTOM: API langsam" in state_msg and "- SCOPE [learner]: nur Org A" in state_msg

    view = (await client.get(f"/tutor/session/{sid}", headers=auth(a))).json()
    assert view["incident"]["model"]["hypotheses"][0]["h"] == "fehlender Index"
    assert (await client.patch(f"/tutor/session/{sid}/incident", json={"field": "scope", "value": "x"},
                               headers=auth(b))).status_code == 404
    assert (await client.patch(f"/tutor/session/{sid}/incident", json={"field": "nope", "value": "x"},
                               headers=auth(a))).status_code == 422


async def test_first_message_with_a_customer_problem_skips_onboarding(api: Any, users: tuple[UUID, UUID]) -> None:
    client, svc, fake = api
    a, _ = users
    sid = (await client.post("/tutor/session", json={}, headers=auth(a))).json()["id"]
    q = "Welche Meldung genau?"
    fake.script += [
        text_reply("Erst die Fakten.", turn={"mode": "incident", "language": "de", "persona_on": True, "speech": q,
                                             "next_question": q, "incident": {"symptom": "Inserts schlagen fehl"}}),
        text_reply("Gut.", turn={"mode": "lesson", "language": "de", "persona_on": True, "speech": q,
                                 "next_question": q}),
    ]
    res = parse_sse((await client.post("/tutor/turn", headers=auth(a), json={
        "session_id": sid, "text": "Kunde meldet: Seit dem Deploy schlagen Inserts mit 42501 fehl."})).text)
    assert res[0] == ("mode", {"mode": "incident", "reason": "customer_problem"})
    system = [m["content"] for m in fake.requests[0]["messages"] if m["role"] == "system"][-1]
    assert "MODE: incident" in system and "Onboarding step" not in system and "FIRST TURN" not in system
    assert (await svc.store.session(a, UUID(sid)))["mode"] == "incident"

    # The model may leave incident mode later; onboarding still does not come back in this session.
    await client.post("/tutor/turn", json={"session_id": sid, "text": "Ok"}, headers=auth(a))
    assert await svc.store.onboarding_step(a, UUID(sid)) is None


async def test_session_end_is_stored_and_carried_into_the_next_session(api: Any, users: tuple[UUID, UUID]) -> None:
    client, svc, fake = api
    a, _ = users
    first = (await client.post("/tutor/session", json={}, headers=auth(a))).json()["id"]
    end = {"understand": ["GRANT is checked before RLS"], "proved": [], "still_wrong": ["policy vs grant order"],
           "retrieval_questions": ["Which SQLSTATE comes from a missing grant?", "What does RLS do to a SELECT?",
                                   "Where do you see the role PostgREST switched to?"],
           "next_case": "An insert works for anon but not for authenticated."}
    fake.script += [text_reply("Gut, Schluss für heute.", turn={"mode": "lesson", "language": "de",
                                                               "persona_on": True, "speech": "Schluss für heute.",
                                                               "session_end": end}),
                    text_reply("Weiter.")]
    await client.post("/tutor/turn", json={"session_id": first, "text": "fertig"}, headers=auth(a))
    async with svc.store.pool.connection() as conn:
        cur = await conn.execute("select summary, ended_at is not null from tutor.session where id = %s", (first,))
        summary, ended = await cur.fetchone() or (None, False)
    assert ended and summary is not None and summary["next_case"] == end["next_case"]

    second = (await client.post("/tutor/session", json={}, headers=auth(a))).json()["id"]
    await client.post("/tutor/turn", json={"session_id": second, "text": "Hallo"}, headers=auth(a))
    system = [m["content"] for m in fake.requests[-1]["messages"] if m["role"] == "system"][-1]
    assert "- policy vs grant order" in system and "- Which SQLSTATE comes from a missing grant?" in system
