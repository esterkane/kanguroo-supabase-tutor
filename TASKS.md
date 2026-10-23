# TASKS — ordered backlog for Claude Code

Work top to bottom. One task per session where possible. Mark `[x]` when `make check`
is green and the task's test exists. Skill to load is in brackets.

## Phase 0 — Lab stack

- [x] T0.1 `Makefile` with targets `up down reset smoke dev check refresh lint` [supabase-local-lab]
- [x] T0.2 `.env.example`, `.gitignore`, `pyproject.toml` (uv), `frontend/package.json` (Vite+TS+Tailwind) [supabase-local-lab]
- [x] T0.3 `npx supabase init`; enable `vector`, `pg_cron`, `pgtap` in `config.toml`; Postgres 17 [supabase-local-lab]
- [x] T0.4 Apply `supabase/migrations/20261021000000_tutor_core.sql`; fix anything the CLI rejects; seed `tutor.topic` from `docs/curriculum.yaml` [supabase-local-lab]
- [x] T0.5 `scripts/lab_db.sh`: create database `lab` with roles anon/authenticated/service_role + `auth.uid()` shim + `request.jwt.claims` support [supabase-local-lab]
- [x] T0.6 `scripts/lab.py install|reset|list <slug>`; install `labs/01-rls-vs-grant` [broken-labs]
- [x] T0.7 pgTAP: schema exists, RLS enabled on all `tutor.*` user tables, `hybrid_search` callable [pgtap-tests]
- [x] T0.8 `make smoke` [supabase-local-lab]

## Phase 1 — Grounded text tutor

- [x] T1.1 `scripts/ingest_llms.py` end-to-end against local stack (dry-run → real); record `embedding_model` [llms-txt-ingest]
- [x] T1.2 `backend/tutor/retrieval.py` `Retriever` protocol + `PgHybridRetriever`; unit test with 3 fixture chunks [hybrid-search-pgvector]
- [x] T1.3 `backend/tutor/tools.py` — `search_docs`, `web_search` (gated), `run_lab_sql`, `ledger_read`, `ledger_update`, `lab_control` with JSON schemas from `prompts/tools.md` [socratic-tutor-loop]
- [x] T1.4 `backend/tutor/prompt.py` — assembles system prompt from `prompts/` (master + runtime + mode + ledger summary + session language) [socratic-tutor-loop]
  - Persona voice + few-shots: `prompts/persona/kaenguru_persona.yaml` (from the AuDHS Tutor). Its
    `system_prompt` names AI/ML/LLMs/web dev as the subject; override that line with Supabase/PostgreSQL,
    fill `{learner_name}`, and keep the "neutral on request" few-shot.
- [x] T1.5 `backend/tutor/orchestrator.py` — Claude tool loop with streaming; emits `TutorTurn`; max 6 tool calls/turn [socratic-tutor-loop]
- [x] T1.6 `backend/tutor/guard.py` — citation coverage, secret scan, destructive-SQL warning, exactly-one-question, incident headings [socratic-tutor-loop]
- [x] T1.7 `backend/tutor/lab_runner.py` — SAVEPOINT sandbox, role switch, claims, EXPLAIN capture, deny-list, 5 s statement_timeout [broken-labs]
  - Implement `backend.tutor.tools.LabTools` (`run_sql` + `control`: install/reset/status/hint/check/list)
    and pass it as `ToolContext.lab`; until then both lab tools return "not available" to the model.
- [x] T1.8 `backend/tutor/router.py` — `POST /turn` (SSE), `GET /session/{id}`, `GET /ledger`, `POST /lab/{slug}/{action}`; JWT verification via Supabase JWKS [socratic-tutor-loop]
  - Done: POST /session, GET /session/{id}, POST /turn (SSE), GET /ledger, GET /labs, POST /lab/{slug}/{action};
    ES256 JWKS verification; verbatim message storage (migration 20261021030000). `/internal/refresh` moves to T1.12.
- [x] T1.9 `frontend/src/tutor` — chat panel, lesson sidebar (objective, main path / rabbit hole / return point), ledger view, Mermaid renderer, mode switches (hint/show me/skip/neutral/rabbit hole/recap/exam/slower/faster) [tutor-viz]
  - Done incl. login (local Supabase Auth), session resume, SSE streaming with tool chips and guard
    rewrites, lab console (`POST /tutor/lab/sql`) with EXPLAIN plan tree, labs panel, ledger tab.
- [x] T1.10 First-turn flow: persona intro + ONE opening question; then request-flow lesson; then lab 01 handed over [socratic-tutor-loop]
  - Done: onboarding step derived per session (opening → request_flow → lab_handover) until lab 01 was handed
    over once; handover via lab_control install (model sees the real report), `lab` SSE event, console preset.
  - [ ] Decide: PostgreSQL's own hint on 42501 ("GRANT SELECT ON lab01.orders TO authenticated") gives lab 01
    away in the console. Keep (real server output) or show hints only after the learner asks?
- [x] T1.11 Evals: `evals/grounding.jsonl` (30), `evals/socratic.jsonl` (15), `evals/safety.jsonl` (10) + `scripts/eval.py` [tutor-evals]
  - Results 2026-10-23 (recorded in evals/recordings/): retrieval recall@8 0.88 / MRR 0.73, grounding 30/30,
    persona 8/8, incident 6/6, safety 10/10 (after the learner-secret guard fix), socratic 11/15 under the
    calibrated Sonnet judge (27% on the first run; lesson rules + guard question rule raised it).
  - [ ] Decide the Socratic standard: Saru's reference path hands over fixes in comparisons (e.g. the composite
    index) and the judge agrees with it only ~56%; the skill's spec says "no complete solution unless show me".
    Pick one, then re-run `make eval-calibrate` and `make evals`.
  - [ ] Compound one-sentence questions ("X, und Y?") still fail 4 socratic cases; lesson.md rule added
    2026-10-23, not yet re-run.
  - Include incident→lesson cases from `docs/examples/slow-query-tutoring-path.md` (one question per turn,
    credit-then-correct, "what this does not prove", meaning-preserving fix).
- [ ] T1.12 `pg_cron` job `refresh_docs` weekly calling the ingest via `pg_net` to FastAPI `/internal/refresh` (local only) [llms-txt-ingest]

## Hands-on track on real data (Olist e-commerce, started 2026-10-21)

Lessons are tested against the learner's real local stack: real rows, real plans, real errors.
Dataset: kaggle.com/datasets/olistbr/brazilian-ecommerce in `data/olist/` (gitignored), imported by
`make olist` into the `lab` DB (schemas `olist_staging` raw text, `olist` typed + synthetic `app_users`).
Synthetic additions (identities, volume growth) are always labelled as such in the lab README.

- [x] O1 `make olist`: CSV → staging → typed (`datasets/olist/transform.sql`), keys, 96,096 synthetic app_users
- [x] O2 Lab 09 revenue join fan-out (phase A): real data inflates delivered revenue by 28.2 %
- [x] O3 Lab 04 missing index (phase H, = T2.3 lab 04): real orders grown 20× (1.99M rows), Seq Scan+Sort 37 ms
  → composite index 0.3 ms on Saru's Mac
- [ ] O4 Workload lab (phase H): generate repeated real queries, find the top query in `pg_stat_statements`
  by total vs mean time (needs the extension in the lab DB, created by the import script, not by learners)
- [x] O5 Locks lab (phase I, = T2.3 lab 05) on `olist.orders`: open transaction in session a updating an order,
  session b blocked → `pg_locks` / `pg_blocking_pids` / lock_timeout 55P03 (runner sessions exist)
- [x] O6 Dead tuples lab (phase I, = T2.3 lab 06): mass status updates on the grown table with autovacuum off for
  that table → `n_dead_tup`, bloat, VACUUM
- [ ] O7 RLS through the real API (phase D): a slice of Olist in the main local stack exposed via PostgREST;
  JWTs for synthetic app_users; the real-data trap that `customer_id` is per order while the person is
  `customer_unique_id`. Needs a second, equally sandboxed runner target (main DB) — decide in an ADR first.
- [ ] O8 Pooler lab (phase J, = T2.3 lab 07) against local Supavisor (enabled in config.toml)
- [ ] O9 Storage lab (phase F): product-image bucket policy / signed URLs keyed by real product ids
- [ ] O10 Realtime lab (phase F): order status updates not arriving (table not in the publication / RLS)
- [ ] O11 Edge Function lab (phase F): webhook returns 500 (missing secret), read the function logs

## Proposed — reuse from Saru's other repos (surveyed 2026-10-21, not yet scheduled)

Paths are in the sibling clones under ~/projects. Order = suggested order.

- [ ] R1 Retrieval eval harness: port `audhs-tutor/backend/app/evals/retrieval.py` + `scripts/eval_retrieval.py`
  (recall@k/MRR, labels by URL/heading + phrase, baseline JSON, fail on >0.05 drop). Feeds T1.11; do before R2.
- [ ] R2 Reranker + per-document cap: `audhs-tutor/backend/app/knowledge/rerank.py` (`FastembedReranker`,
  `cap_per_document`, `candidate_count`) as the `Reranker` in `retrieval.py`, behind `RERANK=1`; measure with R1.
- [ ] R3 Ingest freshness: send `If-None-Match` (ETag is stored but unused) and reuse embeddings per
  (content_hash, embedding_model) so a changed page only re-embeds changed chunks. Makes T1.12 cheap.
- [ ] R4 Banned phrases / sentence caps from `audhs-tutor/backend/app/evals/hardchecks.py` as guard warnings.
- [ ] R5 Per-turn cost + cache-hit logging (`tutor.model_call`), idea from `audhs-tutor/.../models_ai/budget.py`;
  the orchestrator already sums cache read/write tokens in `Final.usage`.
- [ ] R6 Recorded LLM replies for offline evals: `opportunity-intelligence/src/oi/providers/llm.py` (`FixtureProvider`).
- [ ] R7 Judge calibration for socratic/grounding evals: `lernapp/evals/calibration.py`.
- [ ] R8 T2.5 spaced review with FSRS (py-fsrs) as in `audhs-tutor/backend/app/kernel/memory.py` instead of SM-2.
- [ ] R9 T2.6 server TTS via the running Kokoro container (`audhs-tutor/backend/app/voice/tts.py`, sentence
  streaming in `voice/loop.py`) — English only: Kokoro v1 has no German voices, German stays on Web Speech/Piper.
- [ ] R10 ADR-004 cheap local pre-steps (summarise pasted logs, "did the learner answer?") via a small
  Claude/Ollama switch like `compass/llm.py`, not the full audhs gateway.
- Not planned: moving the corpus to Qdrant/Elasticsearch (ADR-001; a `QdrantRetriever` only for the AuDHS host
  corpus in T3.1), Jina embeddings (re-ingest + API cost), OATutor BKT (fixed params; FSRS fits better).

## Phase 2 — Voice, incident mode, labs

- [ ] T2.1 Web Speech STT/TTS; push-to-talk and hands-free; `speech` track playback [tutor-voice]
- [ ] T2.2 Incident mode: structured incident model form that the model fills progressively [socratic-tutor-loop]
- [ ] T2.3 Labs 02–08: missing grant, wrong JWT identity, slow RLS policy + missing index, lock contention, long transaction vs autovacuum, connection exhaustion (pool sim), migration drift [broken-labs]
  - Lab 04 (missing-index) should reproduce `docs/examples/slow-query-tutoring-path.md`: orders table,
    `customer_id` filter + `created_at desc limit 20`, then the index-used-but-slow follow-up (dead tuples).
- [ ] T2.4 Web search adapter with tiering + date + redaction; evals for "label community evidence" [socratic-tutor-loop]
- [ ] T2.5 Spaced review scheduler (`next_review`), session-end summary block (5 headings) [socratic-tutor-loop]
- [ ] T2.6 Optional server TTS (Piper/Kokoro) cached in Storage [tutor-voice]

## Phase 3 — Sub-module and hosted

- [ ] T3.1 Mount router + React route into AuDHS Tutor; shared auth
- [ ] T3.2 Hosted target switch (read-only inspection of a Free project for Supavisor/Reports lessons)
- [ ] T3.3 Case-study generator from redacted GitHub issues; exam mode
