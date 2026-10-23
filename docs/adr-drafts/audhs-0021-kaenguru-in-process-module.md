<!-- DRAFT for ~/projects/audhs-tutor/docs/adr/0021-kaenguru-in-process-module.md.
     Written in the Känguru repo on 2026-10-23; Saru creates the real ADR in AuDHS with `/adr`.
     Nothing in audhs-tutor has been changed. Status stays Proposed until Saru accepts it. -->

# 0021 — Känguru Supabase tutor as an optional in-process module

Date: 2026-10-23
Status: Proposed

## Context

The owner wants the Känguru tutor (`~/projects/kanguroo-supabase-tutor`: a Socratic Supabase/PostgreSQL
support tutor with hands-on labs) inside AuDHS: its FastAPI router mounted in the AuDHS backend and its React
UI as an AuDHS route, sharing the owner's identity (Känguru T3.1, option B "in-process" chosen 2026-10-23 over
a sidecar or a link-out).

Känguru is not built like an AuDHS slice and touches several binding decisions:

- State: Känguru keeps its learner data, docs corpus (pgvector), labs and audio cache in a local Supabase
  stack (Postgres + Auth + Storage, schema `tutor`, separate database `lab`). AuDHS state is SQLite + Qdrant.
- Identity: Känguru authorises every request with a Supabase JWT and relies on Postgres RLS
  (`auth.uid()`); AuDHS has no login, one owner (`api/deps.py: get_learner → get_or_create_owner`).
- Models (ADR-0001, ADR-0010): Känguru calls Claude through the Anthropic SDK directly (streaming tool loop,
  prompt caching, thinking blocks), not through `ModelGateway`/LiteLLM, and writes no `model_call` rows.
- Pedagogy (CLAUDE.md guardrails): Känguru is Socratic by default; AuDHS is explicit by default, Socratic
  opt-in per session, never silently switched.
- Learner model (ADR-0004): Känguru has its own mastery ledger with FSRS in Postgres; the AuDHS kernel owns
  memory and competency.
- Sandbox (ADR-0008): Känguru runs model-written SQL, in a disposable `lab` database.
- Voice (ADR-0011): Känguru can use a local Piper server for German TTS; ADR-0011 keeps German TTS visibly
  unavailable.

## Decision

1. **Optional and off by default.** `KAENGURU_ENABLED=false` in `core/config.py`. When off, nothing is
   imported, mounted or required; `make dev`, `make test` and every existing slice behave exactly as today.
2. **Packaging.** The AuDHS backend installs Känguru as an editable path dependency (uv source
   `kaenguru-tutor = { path = "../../kanguroo-supabase-tutor", editable = true }`) in an optional dependency
   group `kaenguru`, which brings `psycopg[binary,pool]`, `anthropic`, `sse-starlette`, `pyjwt[crypto]`.
   Känguru never imports AuDHS code; AuDHS imports only `TutorService`, `router` and the host hooks below.
3. **Mounting.** In `lifespan`, when enabled: build Känguru's `TutorService` from AuDHS settings
   (`KAENGURU_DB_URL`, `KAENGURU_SUPABASE_URL`, `KAENGURU_SECRET_KEY`, `KAENGURU_USER_ID`, `ANTHROPIC_API_KEY`
   — all via `core/config.py`, names in `.env.example`), store it on `app.state.kaenguru`, and
   `include_router(kaenguru.router, prefix="/api/kaenguru")`. Startup fails loudly if enabled but the
   Supabase stack is unreachable; it never falls back silently.
4. **Shared identity.** In-process, the host is trusted: AuDHS passes a host verifier that maps the AuDHS
   owner to one Supabase auth user (`KAENGURU_USER_ID`, created once with Känguru's `make dev-user`). No
   login form, no Supabase key or JWT in the browser. Känguru still writes as that user through
   `set_config('request.jwt.claims', …)`, so its RLS keeps working; `learner_id` (ULID) ↔ Supabase user id
   is a fixed config mapping, one learner (multi-user mapping is a follow-up when AuDHS gets users).
5. **Models and budget.** Känguru keeps its own Anthropic client: the tool loop needs streaming tool use,
   prompt caching and thinking-block handling that the gateway does not expose. To keep ADR-0001/0010
   observable and capped, the host passes two hooks: `before_turn()` (refuses with 503 when the AuDHS daily
   hosted budget is spent) and `on_model_call(usage, model, ms)` (writes one AuDHS `model_call` row per
   Känguru API call against a hosted registry entry `kaenguru-claude`, TaskClass `tutor_deep`, with cost).
   The model id lives in that registry entry, not in AuDHS code.
6. **Pedagogy.** Inside AuDHS, every Känguru session starts with an explicit choice "Explicit or Socratic?",
   default Explicit. Explicit mode: one step, worked explanation, then one check question; Socratic only when
   chosen for that session. The choice is shown in the UI and never changes without the learner.
7. **Learner model.** Känguru's ledger stays its own (topic mastery for its curriculum) and is not part of the
   AuDHS mastery view yet. Follow-up: Känguru reports lab outcomes and graded answers to the host as
   `competency_evidence` events so the AuDHS kernel owns the durable state; then Känguru's FSRS scheduling
   is replaced by AuDHS memory items or kept only as a hint.
8. **Sandbox.** Känguru's lab runner counts as the resource-limited backend sandbox of ADR-0008 for SQL:
   separate `lab` database on the local Supabase Postgres, every statement in a rolled-back savepoint unless a
   lab declares the step persistent, statement and lock timeouts, a deny-list (no file access, COPY PROGRAM,
   dblink, role or database DDL, ALTER SYSTEM, signalling foreign backends), no network from SQL.
   Retrieved docs and web results reach the model only inside tagged untrusted blocks in tool results.
9. **Voice.** When mounted, Känguru uses browser voices only (`TUTOR_TTS=browser`). Using its Piper server
   for German needs an amendment to ADR-0011 first.
10. **UI.** AuDHS route `/kaenguru` in `app/App.tsx`, rendering Känguru's `TutorApp` in a host-auth mode
    (token provided by the host proxy, no Supabase client) inside the AuDHS shell; it runs under React 19 and
    Tailwind 4, which AuDHS already uses. Single-task screen; no autoplay; the parking lot stays reachable.

## Consequences

Positive
- One app, one identity, no second login; the owner's Supabase/PostgreSQL practice lives next to the AI
  curriculum.
- AuDHS stays unchanged and testable without Supabase when the module is off.
- Hosted Känguru calls become visible in AuDHS `model_call` and count against the AuDHS daily budget.

Negative
- A second persistent store (local Supabase: Postgres, Auth, Storage, cron) runs alongside SQLite + Qdrant
  while enabled; `make dev` needs `npx supabase start` in the Känguru repo first.
- AuDHS's environment grows by psycopg, anthropic, sse-starlette and Känguru itself (group `kaenguru`).
- Two learner models until follow-up 7 lands; two FSRS schedulers meanwhile.
- A direct Anthropic client outside the gateway, contained by the hooks in decision 5.

Follow-ups (Känguru side first)
- Done in Känguru on 2026-10-23: `kaenguru_tutor` (`HostConfig`, `build_service`, `HostVerifier`, `HostHooks`
  with `before_turn` / `on_model_call`, `router`), editable package layout (verified from a clean venv),
  `session.delivery` with an explicit delivery prompt, `TutorApp` host mode and delivery chooser.
- AuDHS side after acceptance: config keys, optional group, lifespan mount, `/kaenguru` route, contract tests
  with a fake Anthropic client (skipped when Supabase is not running), docs (ARCHITECTURE, HANDOFF).
- Competency-evidence bridge (decision 7); ADR-0011 amendment if German server TTS is wanted inside AuDHS.

## Alternatives considered

- **Sidecar with a token bridge**: Känguru as its own service behind an AuDHS reverse proxy. Weaker coupling,
  but a second running service and the proxy layer; not chosen (owner decision 2026-10-23).
- **Link-out**: open the standalone Känguru app; no shared identity, so it does not meet the goal.
- **Port Känguru onto SQLite/Qdrant**: would drop pgvector/RLS/real Postgres behaviour, which is the subject
  being taught (labs need a real Postgres with roles, RLS, locks and VACUUM).

## Evidence / sources

- Survey 2026-10-23: `backend/app/api/deps.py` (owner-only identity), `backend/app/main.py` (lifespan),
  `backend/app/api/__init__.py` (`APIRouter(prefix="/api")`), `frontend/src/app/App.tsx` (routes),
  frontend already on React 19.2, Tailwind 4.3, mermaid 12, react-markdown 10.
- Känguru: `docs/ARCHITECTURE.md` §8 (standalone vs sub-module), `docs/INTEGRATION-AUDHS.md` (options),
  `backend/tutor/router.py`, `backend/tutor/service.py`, `backend/tutor/lab_runner.py` (sandbox rules).
- AuDHS ADR-0001, 0004, 0008, 0010, 0011 and the CLAUDE.md pedagogy guardrails.
- Open in AuDHS since 2026-10-15: uncommitted ask-context-proposal work; this ADR's implementation touches
  none of those files.
