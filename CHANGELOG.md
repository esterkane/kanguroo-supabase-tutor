# Changelog
- 2026-10-21 scaffold: architecture, decisions, roadmap, CLAUDE.md, TASKS.md, 9 skills, 2 agents,
  prompts (master + runtime + schema + tools + 5 modes), core migration + pgTAP, ingest script
  (+ offline tests), lab DB script, lab 01, curriculum, Makefile.
- 2026-10-21 Phase 0 (T0.1–T0.8): supabase init (CLI 2.121.0, PG 17, pooler on); migration fix — qualify
  pgvector `<=>` as `operator(extensions.<=>)` under `search_path = ''`; generated seed (63 topics, lab 01);
  psql-free scripts (`db.py`, `lab_db.py` with ''-safe auth shim, `lab.py` list/install/reset/check/solve/sync,
  `seed.py`, `smoke.py`); pgTAP 16 tests incl. RLS on every tutor table; `make test-labs` checks each lab
  FAILS broken and PASSES solved; Vite+React+TS+Tailwind shell with vitest; dev ports 8020/5180;
  persona `prompts/persona/kaenguru_persona.yaml` added for T1.4.
- 2026-10-21 T1.1 ingest end-to-end: depth-1 expansion to guide pages + KB articles (831 active sources,
  10,352 chunks, nomic-embed-text); llms-full.txt split on `---` + H1 and only pages without their own URL
  kept; KB copies of docs troubleshooting articles skipped (broken /kb/ links); missing sources retired;
  raw copies in data/corpus; migration 20261021010000 makes hybrid_search return one row per chunk text
  (docs/guides wins ties) + pgTAP 002; `make search Q=...`; smoke asserts real hits once ingested.
- 2026-10-21 T1.2 retrieval: `backend/tutor/schemas.py` (Chunk), `backend/tutor/retrieval.py` (Retriever /
  Embedder / Reranker protocols, Ollama + OpenAI embedders, PgHybridRetriever, search_docs product
  aliases); fix: hybrid_search pins hnsw.iterative_scan + ef_search (filtered searches returned 0 semantic
  hits) — migration 20261021020000 + pgTAP 003; 7 retrieval tests (offline + 3 fixture chunks in local DB).
- 2026-10-21 T1.3 tools: `backend/tutor/tools.py` (TOOLS == prompts/tools.md, pydantic input models, dispatch
  with 6-call / 2-web budget, gated web_search with untrusted wrapping + domain tiers), `ledger.py` (PgLedger
  via `set local role authenticated` + claims, RLS-enforced), `db.as_user`; 23 new tests incl. owner-only ledger.
- 2026-10-21 T1.4 prompt: `backend/tutor/prompt.py` builds `system` blocks — cached static prefix (master +
  persona voice retargeted to Supabase/PostgreSQL + runtime + TutorTurn schema + 63 topic slugs), cached mode
  block, uncached session state (date, language, objective, ledger weakest/recent, lab, still-wrong);
  persona few-shots dropped (off-topic). 13 tests.
- 2026-10-21 T1.5 orchestrator: `backend/tutor/orchestrator.py` streams a Claude tool loop (claude-sonnet-5-5,
  adaptive thinking, effort medium, server-side refusal fallback, eager tool-input streaming) and ends in a
  parsed `TutorTurn` (`schemas.py`, `turn_parser.py`: one repair, then `unstructured`). History is append-only:
  `system` is now fixed per session and mode + session state go in as a mid-conversation system message
  (prompt.py split); `drop_block` as safety net. Contract change: the model omits `text` from the JSON (app
  fills it). Reference tutoring path from Saru's slow-query session added (`prompts/examples/`,
  `docs/examples/`). `make turn Q=...` for a live turn. 16 new tests (fake client, real SDK types).
