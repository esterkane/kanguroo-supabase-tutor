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

    await client.post("/tutor/turn", json={"session_id": sid, "text": "Weiter"}, headers=auth(a))
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
