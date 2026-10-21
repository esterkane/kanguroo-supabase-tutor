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
- 2026-10-21 T1.6 guard: `backend/tutor/guard.py` checks one question, citation markers vs entries, cited URLs
  must come from a tool (tier not inflated, tier 4 labelled), uncited price/plan/limit/version claims,
  secrets (JWT, sb_secret_, sk-ant-, real connection passwords), destructive SQL / disabled RLS outside a
  `> ⚠ Risk:` block, incident model, speech length/markup, claimed execution without run_lab_sql. Block →
  one rewrite (`Rewrite` event for the UI), then flagged; secrets always redacted. 33 tests.
- 2026-10-21 T1.7 lab runner: `backend/tutor/lab_runner.py` implements `LabTools` — run_lab_sql in the `lab`
  DB as anon/authenticated/postgres with claims, savepoint per statement, rolled back unless lab.yaml declares
  the step persistent, ≤200 rows, EXPLAIN (ANALYZE, BUFFERS) JSON, 5 s statement / 4 s lock timeout,
  deny-list (DB/role DDL, cluster-wide effects, file access, transaction control, role switching), named
  sessions a/b holding locks ≤120 s; lab_control list/install/reset/status/hint/check with tutor.lab_run
  bookkeeping (tests[], hints_used, outcome) via RLS. `make turn` now has lab tools. 31 tests.
- 2026-10-21 Hands-on real-data track: Olist dataset downloaded (Kaggle, 44.7 MB, gitignored), `make olist`
  imports staging + typed schema + synthetic app_users into the lab DB (~7 s); lab 09 revenue join fan-out
  (real 28.2 % inflation) and lab 04 missing index (real orders grown 20×; 37 ms → 0.3 ms) with pgTAP checks
  both ways; labs declare `requires: [olist]` (skipped/explained when missing); ADR-011; TASKS O1–O11.
  Reference tutoring path for building the support lab (`prompts/examples/support_lab_plan.md`).
- 2026-10-21 Proposed reuse backlog R1–R10 from Saru's other repos in TASKS.md (survey, not scheduled).
- 2026-10-21 O5 + O6 real-data ops labs. Lab 05 lock contention: a real `nightly-export` session holds FOR UPDATE
  row locks idle in transaction; the webhook update gets 55P03; evidence via pg_stat_activity and xmax = backend_xid;
  fix = terminate the job, lock-free export, lock_timeout on the function. Lab 06 dead tuples: autovacuum off +
  10 status-sync rewrites → 994,410 dead tuples, 155 MB vs 14 MB; VACUUM clears them but not the size (stretch:
  VACUUM FULL). Runner: lab scenario sessions (application_name, TTL up to 15 min), pg_terminate/cancel_backend
  only for the runner's own lab sessions, VACUUM as a declared non-transactional step, timeouts on checks.
- 2026-10-21 Repo published: github.com/esterkane/kanguroo-supabase-tutor (public); repo-local git identity is
  the GitHub no-reply address.
- 2026-10-21 T1.8 router: `backend/tutor/router.py` (POST /session, GET /session/{id}, POST /turn as SSE with
  token/tool_call/tool_result_summary/rewrite/turn/error, GET /ledger, GET /labs, POST /lab/{slug}/{action}),
  `auth.py` (Supabase JWKS, asymmetric algorithms only, role authenticated), `service.py` (TutorService, TurnStore
  persisting API messages verbatim in order, one LabRunner per session, one turn at a time per session);
  migration 20261021030000 (turn.message jsonb, turn.seq, role 'system') + pgTAP 004; `make dev-user` creates a
  local dev learner (credentials only in .env); `make dev` loads .env.local + .env. Verified end-to-end with a
  real local Auth token; /turn returns 503 until ANTHROPIC_API_KEY is set. 10 new tests.
- 2026-10-21 T1.9 browser UI: login against local Supabase Auth, session resume/new, chat with SSE streaming
  (tool chips, guard rewrite note), Markdown/GFM, lazy strict Mermaid with fallback, citations with tiers,
  sidebar tabs (lesson path + mode commands, labs, ledger), lab console via new `POST /tutor/lab/sql` (same
  sandbox as the tutor) with EXPLAIN plan tree and "send to tutor"; de/en strings. Verified in the browser
  with a live turn and lab 04's real plan. Fixes: effect returned scrollIntoView's Promise (Chromium crash);
  guard QUESTION_NOT_IN_TEXT now tolerates reworded questions. `make env` writes frontend/.env.local.
