"""Host integration (T3.1; AuDHS ADR 0021 draft): what a host app needs to mount the tutor in-process.

The host is trusted in-process, so it supplies the learner's identity itself (`HostVerifier`: one Supabase auth
user per host learner, no JWT in the browser) and two hooks: `before_turn` may refuse a turn (e.g. the host's
daily budget is spent) and `on_model_call` receives every Anthropic API call with its usage, so the host can log
it in its own accounting. Hosts import from `kaenguru_tutor`, never from deeper modules.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

from fastapi import Request


@dataclass(frozen=True)
class ModelCall:
    """One Anthropic API call of a tutor turn (a turn with tools makes several)."""
    model: str
    usage: dict[str, int]
    ms: float
    kind: str = "tutor_turn"


class HostRefusal(Exception):
    """Raised by `before_turn` to stop a turn; the router answers with `status_code` and the message."""

    def __init__(self, message: str, status_code: int = 503) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class HostHooks(Protocol):
    async def before_turn(self, user_id: UUID) -> None: ...

    async def on_model_call(self, user_id: UUID, call: ModelCall) -> None: ...


class Verifier(Protocol):
    async def user_id(self, request: Request) -> UUID: ...


@dataclass(frozen=True)
class HostVerifier:
    """In-process identity: every request belongs to the host's learner, mapped to one Supabase auth user.

    The tutor still writes as that user (request.jwt.claims), so Postgres RLS keeps applying."""
    user: UUID

    async def user_id(self, request: Request) -> UUID:
        return self.user


@dataclass(frozen=True)
class HostConfig:
    db_url: str                       # the local Supabase Postgres (database `postgres`, schema `tutor`)
    supabase_url: str                 # API URL of the local stack, e.g. http://127.0.0.1:54321
    user_id: UUID                     # Supabase auth user the host learner maps to (`make dev-user`)
    anthropic_api_key: str | None = None
    lab_db_url: str | None = None     # default: same server, database `lab`
    refresh_token: str | None = None  # weekly docs refresh endpoint; None leaves it off
    extra: dict[str, Any] = field(default_factory=dict)


def build_service(cfg: HostConfig, hooks: HostHooks | None = None) -> Any:
    """A TutorService for a host: host identity, host hooks, browser voices, no web search (ADR 0021)."""
    from anthropic import AsyncAnthropic
    from psycopg_pool import AsyncConnectionPool

    from backend.tutor.lab_runner import lab_pool
    from backend.tutor.ledger import PgLedger
    from backend.tutor.refresh import RefreshManager
    from backend.tutor.retrieval import PgHybridRetriever, embedder_from_env
    from backend.tutor.service import TutorService

    lab_url = cfg.lab_db_url or cfg.db_url.rsplit("/", 1)[0] + "/lab"
    app_pool = AsyncConnectionPool(cfg.db_url, min_size=1, max_size=8, open=False)
    return TutorService(
        app_pool=app_pool, lab_pool=lab_pool(lab_url, min_size=1, max_size=4), lab_url=lab_url,
        verifier=HostVerifier(cfg.user_id),
        retriever=PgHybridRetriever(app_pool, embedder_from_env()), ledger=PgLedger(app_pool),
        anthropic=AsyncAnthropic(api_key=cfg.anthropic_api_key) if cfg.anthropic_api_key else None,
        refresh=RefreshManager(app_pool, cfg.db_url, cfg.refresh_token),
        hooks=hooks,
    )
