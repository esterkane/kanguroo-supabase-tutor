"""Känguru Tutor — mountable FastAPI package.

Module map (implemented in TASKS.md order):
  schemas.py       TutorTurn, Chunk, GuardFinding (pydantic, extra='forbid')
  prompt.py        assemble system prompt from prompts/ (cached static prefix)
  tools.py         tool JSON schemas (must equal prompts/tools.md) + dispatch
  retrieval.py     Retriever protocol, PgHybridRetriever, optional Reranker
  web_search.py    gated adapter; wraps results as untrusted tier-4 data
  lab_runner.py    SAVEPOINT sandbox against LAB_DB_URL, role switch, EXPLAIN
  ledger.py        mastery ledger read/update + spaced review
  guard.py         TutorTurn invariants → GuardFinding[]
  orchestrator.py  Claude tool loop, streaming, repair on guard block
  voice.py         server TTS (Phase 2)
  router.py        FastAPI router: /turn (SSE), /session, /ledger, /lab, /internal/refresh

Host apps mount with:  app.include_router(tutor.router, prefix="/tutor")
This package never imports from a host app.
"""
