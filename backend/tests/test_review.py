"""Spaced review (T2.5): FSRS rating and intervals, ledger scheduling, due topics in the session state."""
from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from psycopg_pool import AsyncConnectionPool

from backend.tutor.ledger import LedgerDelta, LedgerEntry, PgLedger
from backend.tutor.prompt import SessionState, session_block
from backend.tutor.review import due_topics, rating_from_score, review

NOW = datetime(2026, 10, 23, 12, tzinfo=UTC)


@pytest.mark.parametrize(("score", "rating"), [(0, "Again"), (1, "Again"), (2, "Hard"), (3, "Good"), (4, "Good"),
                                                (5, "Easy")])
def test_rating_from_score(score: int, rating: str) -> None:
    assert rating_from_score(score).name == rating


def intervals(scores: list[int]) -> list[int]:
    card: dict[str, Any] | None = None
    now, out = NOW, []
    for s in scores:
        card, due = review(card, s, now)
        out.append((due - now).days)
        now = due  # reviewed exactly when due
    return out


def test_topics_are_scheduled_in_days_and_weak_topics_come_back_sooner() -> None:
    assert intervals([3, 3, 3]) == [2, 11, 46]   # no minute-long learning steps for curriculum topics
    assert intervals([1, 2, 3]) == [1, 1, 3]
    assert intervals([5, 5]) == [8, 66]
    assert intervals([4, 4, 1])[-1] < intervals([4, 4, 4])[-1]  # a lapse shortens the interval


def entry(topic: str, score: int, due: datetime | None) -> LedgerEntry:
    return LedgerEntry(topic=topic, phase="D", title=topic, score=score, evidence="evidence text",
                       last_reviewed=NOW - timedelta(days=3), next_review=due)


def test_due_topics_most_overdue_first_capped() -> None:
    entries = [entry("a", 2, NOW - timedelta(days=1)), entry("b", 4, NOW + timedelta(days=5)),
               entry("c", 1, NOW - timedelta(days=9)), entry("d", 3, None), entry("e", 2, NOW - timedelta(hours=1)),
               entry("f", 2, NOW - timedelta(days=2))]
    assert [e.topic for e in due_topics(entries, NOW)] == ["c", "f", "a"]


def test_session_block_lists_due_reviews_and_last_session() -> None:
    state = SessionState(ledger=[entry("rls-vs-grants", 2, NOW - timedelta(days=4))],
                         due=[entry("rls-vs-grants", 2, NOW - timedelta(days=4))],
                         still_wrong=["mixed up GRANT and RLS order"],
                         retrieval_questions=["A select returns 0 rows without error. Which layer?"])
    block = session_block(state)
    assert "Due for spaced review (FSRS, most overdue first):\n- rls-vs-grants 2/5, due since 2026-10-19" in block
    assert "ONE retrieval question on the first due topic" in block
    assert "- mixed up GRANT and RLS order" in block
    assert "- A select returns 0 rows without error. Which layer?" in block
    assert "Due for spaced review" not in session_block(SessionState())


@pytest.fixture
def learner(db_url: str) -> Iterator[Any]:
    user = uuid4()
    yield user
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute("delete from tutor.mastery_ledger where user_id = %s", (user,))


async def test_ledger_update_schedules_the_next_review(pool: AsyncConnectionPool, learner: Any) -> None:
    ledger = PgLedger(pool)
    before = datetime.now(UTC)
    first = await ledger.update(learner, [LedgerDelta(topic="rls-vs-grants", score=3,
                                                      evidence="predicted 42501 from the grant layer")])
    assert first[0].next_review is not None and first[0].next_review > before + timedelta(days=1)
    weak = await ledger.update(learner, [LedgerDelta(topic="rls-vs-grants", score=1,
                                                     evidence="could not say which layer filters rows")])
    assert weak[0].next_review is not None and weak[0].next_review < before + timedelta(days=2)
    async with pool.connection() as conn:
        cur = await conn.execute("select fsrs_card from tutor.mastery_ledger where user_id = %s", (learner,))
        card = (await cur.fetchone() or [None])[0]
    assert card and card["state"] in (2, 3) and card["stability"] > 0
