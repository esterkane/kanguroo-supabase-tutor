"""Spaced review per curriculum topic with FSRS (T2.5, R8; py-fsrs as in audhs-tutor/backend/app/kernel/memory.py).

Every ledger update with evidence is one review of that topic: the tutor's 0-5 score becomes an FSRS rating and
the card's due date becomes `next_review`. Topics are reviewed across sessions, so there are no minute-long
learning steps: the first review already schedules in days. Weak topics come back sooner by construction
("use spaced review for weaker areas", master instructions).
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Protocol

from fsrs import Card, Rating, Scheduler

DESIRED_RETENTION = 0.9
DUE_CAP = 3  # at most this many due topics go into the session state


def scheduler() -> Scheduler:
    return Scheduler(desired_retention=DESIRED_RETENTION, learning_steps=(), relearning_steps=(),
                     enable_fuzzing=False)


def rating_from_score(score: int) -> Rating:
    """0-1 could not apply it, 2 with heavy help, 3-4 applied it, 5 applied it to a new scenario unaided."""
    if score <= 1:
        return Rating.Again
    if score == 2:
        return Rating.Hard
    if score <= 4:
        return Rating.Good
    return Rating.Easy


def review(card: dict[str, Any] | None, score: int, now: datetime | None = None) -> tuple[dict[str, Any], datetime]:
    """Apply one review; returns the new card (JSON) and its due date."""
    now = now or datetime.now(UTC)
    current = Card.from_dict(card) if card else Card(due=now)  # type: ignore[arg-type]
    updated, _ = scheduler().review_card(current, rating_from_score(score), review_datetime=now)
    return dict(updated.to_dict()), updated.due


class Reviewable(Protocol):
    topic: str
    score: int
    next_review: datetime | None


def due_topics(entries: Sequence[Reviewable], now: datetime | None = None, cap: int = DUE_CAP) -> list[Any]:
    """Topics whose review is due, most overdue first."""
    now = now or datetime.now(UTC)
    due = [e for e in entries if e.next_review is not None and e.next_review <= now]
    return sorted(due, key=lambda e: e.next_review or now)[:cap]
