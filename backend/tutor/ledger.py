"""Mastery ledger: score 0–5 per curriculum topic with evidence, owned by the learner (RLS)."""
from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel, ConfigDict, Field

from backend.tutor.db import as_user


class LedgerDelta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str
    score: int = Field(ge=0, le=5)
    evidence: str = Field(min_length=10)


class LedgerEntry(BaseModel):
    topic: str
    phase: str
    title: str
    score: int
    evidence: str | None
    last_reviewed: datetime
    next_review: datetime | None


class UnknownTopicsError(ValueError):
    def __init__(self, topics: list[str]) -> None:
        super().__init__(f"unknown topic slugs: {', '.join(topics)}")
        self.topics = topics


class LedgerStore(Protocol):
    async def read(self, user_id: UUID) -> list[LedgerEntry]: ...

    async def update(self, user_id: UUID, deltas: list[LedgerDelta]) -> list[LedgerEntry]: ...


class PgLedger:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self.pool = pool

    async def read(self, user_id: UUID) -> list[LedgerEntry]:
        async with as_user(self.pool, user_id) as conn:
            cur = conn.cursor(row_factory=dict_row)
            await cur.execute(
                "select l.topic_slug as topic, t.phase, t.title, l.score, l.evidence, l.last_reviewed, l.next_review"
                " from tutor.mastery_ledger l join tutor.topic t on t.slug = l.topic_slug"
                " order by l.score, l.last_reviewed"
            )
            return [LedgerEntry(**row) for row in await cur.fetchall()]

    async def update(self, user_id: UUID, deltas: list[LedgerDelta]) -> list[LedgerEntry]:
        slugs = [d.topic for d in deltas]
        async with as_user(self.pool, user_id) as conn:
            cur = await conn.execute("select slug from tutor.topic where slug = any(%s)", (slugs,))
            known = {row[0] for row in await cur.fetchall()}
            if unknown := [s for s in slugs if s not in known]:
                raise UnknownTopicsError(unknown)
            for d in deltas:
                # user_id defaults to auth.uid(); the insert/update policies reject any other owner.
                await conn.execute(
                    "insert into tutor.mastery_ledger (topic_slug, score, evidence, last_reviewed)"
                    " values (%s, %s, %s, now())"
                    " on conflict (user_id, topic_slug) do update set"
                    "   score = excluded.score, evidence = excluded.evidence, last_reviewed = now()",
                    (d.topic, d.score, d.evidence),
                )
        return [e for e in await self.read(user_id) if e.topic in slugs]
