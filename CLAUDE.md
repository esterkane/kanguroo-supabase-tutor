# CLAUDE.md — rules for working in this repo

You are building the **Känguru Tutor**: a Socratic Supabase/PostgreSQL support tutor
on a local Supabase stack, mountable into the AuDHS Tutor. Read `docs/ARCHITECTURE.md`
and `TASKS.md` before writing code. Work `TASKS.md` top to bottom; tick items off.

## Hard rules

1. **No commits, pushes, PRs, or GitHub comments without an explicit go-ahead** from Saru
   in the current session. Prepare the diff and stop.
2. **Never run SQL or CLI commands against a hosted/linked Supabase project.** Local only
   (`--local`, `npx supabase status` URLs). The lab runner targets database `lab` only.
3. **Secrets:** `service_role` and API keys live in `.env` (gitignored). Never put them in
   frontend code, fixtures, docs, or test snapshots. Use `npx supabase status -o env`
   to read local keys; do not hardcode them.
4. **Grounding beats fluency.** Any Supabase/PostgreSQL behaviour you assert in prompts,
   docs or tests must come from the ingested corpus (`search_docs`), the Supabase MCP
   server, or `WebFetch` of the official URL — and carry that URL. If you cannot verify,
   write "unverified" next to it.
5. **Keep token use low.** Scope sessions to one task from `TASKS.md`. Prefer the
   `Explore` sub-agent for repo-wide searches. Do not re-read large files you already have.
6. **Packaging preference:** deliver runnable scripts/Makefile targets, not manual command
   sequences. Every script has `--help` and is idempotent.
7. **Language:** code, identifiers, SQL and commit messages in English. Learner-facing
   strings go through i18n (`de`, `en`); German is the default persona language.

## Stack (do not drift)

- Local Supabase via CLI (Postgres 17, pgvector, pg_cron, pgTAP). Schema `tutor`.
- Backend: Python 3.12, FastAPI, `supabase-py` for Auth/Storage, `psycopg` 3 for SQL,
  `anthropic` SDK with tool use + streaming, `httpx`. Package manager: `uv`.
- Frontend: React 18 + TypeScript + Vite + Tailwind, `@supabase/supabase-js`, `mermaid`,
  Web Speech API. Component style: Kibana-like density, no emoji.
- Tests: `pytest` (backend), `supabase test db` (pgTAP), `vitest` (frontend),
  `evals/` (grounding + socratic + safety).

## Skills

Load the matching skill before starting a task:

| Task | Skill |
|---|---|
| Starting/resetting the stack, lab DB, roles | `supabase-local-lab` |
| Fetching/chunking/embedding the docs corpus | `llms-txt-ingest` |
| Search SQL, indexes, RRF, EXPLAIN on search | `hybrid-search-pgvector` |
| Tutor prompt, tool loop, `TutorTurn`, guard | `socratic-tutor-loop` |
| Writing a new broken lab | `broken-labs` |
| pgTAP tests for schema/RLS/labs | `pgtap-tests` |
| STT/TTS, `speech` track | `tutor-voice` |
| Mermaid/table/plan rendering | `tutor-viz` |
| Eval sets and scoring | `tutor-evals` |

Sub-agents: `db-reviewer` reviews every migration and lab for grant/RLS/lock safety;
`grounding-checker` reviews every prompt and tutor fixture for unverified claims.

## Definition of done (per task)

- Code + test + a one-line entry in `CHANGELOG.md`.
- `make check` green (ruff, mypy, pytest, pgTAP, vitest, tsc).
- No new TODOs without a `TASKS.md` entry.
