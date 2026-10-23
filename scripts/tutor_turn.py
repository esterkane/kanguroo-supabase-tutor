#!/usr/bin/env python3
"""Run one real tutor turn from the terminal (uses API tokens).

Streams the Markdown, shows tool calls, then prints the parsed TutorTurn and token/cache usage.
Uses the local corpus (search_docs) and a fixed local dev learner for the ledger. Needs
ANTHROPIC_API_KEY in .env and the local stack (`make up`).

Usage:
  uv run python scripts/tutor_turn.py "Hallo"
  uv run python scripts/tutor_turn.py --mode incident --lang en "Supabase is slow since yesterday"
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from anthropic import AsyncAnthropic
from db import admin_url, lab_url
from psycopg_pool import AsyncConnectionPool

from backend.tutor.lab_runner import LabRunner, lab_pool
from backend.tutor.ledger import PgLedger
from backend.tutor.orchestrator import Final, Orchestrator, Token, ToolCall, ToolResultSummary
from backend.tutor.prompt import SessionState
from backend.tutor.retrieval import PgHybridRetriever, embedder_from_env
from backend.tutor.tools import ToolContext
from backend.tutor.web import web_from_env

DEV_LEARNER = UUID("00000000-0000-0000-0000-00000000c0de")


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("message")
    ap.add_argument("--mode", default="lesson", choices=["lesson", "incident", "exam", "neutral", "rabbit_hole"])
    ap.add_argument("--lang", default="de", choices=["de", "en"])
    ap.add_argument("--first-turn", action="store_true", help="flag the very first turn of the first session")
    args = ap.parse_args()

    state = SessionState(mode=args.mode, language=args.lang, persona_on=args.mode != "neutral",
                         first_turn=args.first_turn)
    async with AsyncConnectionPool(admin_url(), min_size=1, max_size=2) as pool, \
            lab_pool(lab_url(), min_size=1, max_size=2) as labs:
        runner = LabRunner(labs, lab_url())
        web = web_from_env()  # TUTOR_WEB_SEARCH=on + a search key, same as the backend
        ctx = ToolContext(user_id=DEV_LEARNER, retriever=PgHybridRetriever(pool, embedder_from_env()),
                          ledger=PgLedger(pool), lab=runner, web=web, web_enabled=web is not None,
                          learner_text=args.message)
        orch = Orchestrator(client=AsyncAnthropic())
        print(f"[model {orch.model}, effort {orch.effort}]\n")
        async for event in orch.run_turn(history=[], user_text=args.message, state=state, ctx=ctx):
            if isinstance(event, Token):
                print(event.text, end="", flush=True)
            elif isinstance(event, ToolCall):
                print(f"\n[tool] {event.name} {json.dumps(event.input, ensure_ascii=False)}", flush=True)
            elif isinstance(event, ToolResultSummary):
                print(f"[tool {'error' if event.is_error else 'ok'}] {event.summary[:120]}", flush=True)
            elif isinstance(event, Final):
                turn = event.turn.model_dump(exclude={"text"}, exclude_defaults=True)
                print("\n\n--- TutorTurn (without text) ---")
                print(json.dumps(turn, ensure_ascii=False, indent=2))
                print(f"--- served by {event.model}; usage {event.usage}")


if __name__ == "__main__":
    asyncio.run(main())
