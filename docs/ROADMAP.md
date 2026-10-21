# Roadmap

Each phase has an exit test the tutor itself can run with you.

## Phase 0 — Lab stack (week 1)
- `npx supabase start` works; `scripts/lab_db.sh` creates the `lab` database with
  Supabase roles; `labs/01-rls-vs-grant` can be installed and reset.
- Migration `tutor_core` applied; `supabase test db` runs the pgTAP suite green.
- **Exit:** `make smoke` passes (stack up, schema present, one hybrid search returns rows).

## Phase 1 — Grounded text tutor (weeks 2–3)
- Ingest from `llms.txt`; `search_docs` tool; Claude tool loop; `TutorTurn` output;
  guard; SSE streaming; Mermaid rendering; mastery ledger persisted.
- Opening scenario + request-flow lesson + the first broken RLS/grant lab end-to-end.
- **Exit:** `evals/grounding` ≥ 0.9 citation-coverage on the 30-question set;
  `evals/socratic` 0 direct answers in lesson mode on the 15-prompt set.

## Phase 2 — Voice + incident mode + labs (weeks 4–6)
- Browser STT/TTS; `speech` track; incident-mode templates; 8 labs across
  Phases D, G, H, I, J of the curriculum; spaced review.
- Web search adapter with tiering; weekly corpus refresh via pg_cron.
- **Exit:** a full session from "Supabase is slow" to root cause in a lab, by voice.

## Phase 3 — Sub-module + hosted option (later)
- Mount into AuDHS Tutor; optional hosted Supabase project (Free/Pro) as a
  *second* target so hosted-only topics (Supavisor, PITR, Reports) get real screens.
- Case-study generator from GitHub issues (redacted); exam mode.

## Out of scope for now
- Multi-user classrooms, billing, mobile app, agentic execution on hosted projects.
