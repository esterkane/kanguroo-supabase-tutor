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
- [ ] T1.6 `backend/tutor/guard.py` — citation coverage, secret scan, destructive-SQL warning, exactly-one-question, incident headings [socratic-tutor-loop]
- [ ] T1.7 `backend/tutor/lab_runner.py` — SAVEPOINT sandbox, role switch, claims, EXPLAIN capture, deny-list, 5 s statement_timeout [broken-labs]
  - Implement `backend.tutor.tools.LabTools` (`run_sql` + `control`: install/reset/status/hint/check/list)
    and pass it as `ToolContext.lab`; until then both lab tools return "not available" to the model.
- [ ] T1.8 `backend/tutor/router.py` — `POST /turn` (SSE), `GET /session/{id}`, `GET /ledger`, `POST /lab/{slug}/{action}`; JWT verification via Supabase JWKS [socratic-tutor-loop]
- [ ] T1.9 `frontend/src/tutor` — chat panel, lesson sidebar (objective, main path / rabbit hole / return point), ledger view, Mermaid renderer, mode switches (hint/show me/skip/neutral/rabbit hole/recap/exam/slower/faster) [tutor-viz]
- [ ] T1.10 First-turn flow: persona intro + ONE opening question; then request-flow lesson; then lab 01 handed over [socratic-tutor-loop]
- [ ] T1.11 Evals: `evals/grounding.jsonl` (30), `evals/socratic.jsonl` (15), `evals/safety.jsonl` (10) + `scripts/eval.py` [tutor-evals]
  - Include incident→lesson cases from `docs/examples/slow-query-tutoring-path.md` (one question per turn,
    credit-then-correct, "what this does not prove", meaning-preserving fix).
- [ ] T1.12 `pg_cron` job `refresh_docs` weekly calling the ingest via `pg_net` to FastAPI `/internal/refresh` (local only) [llms-txt-ingest]

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
