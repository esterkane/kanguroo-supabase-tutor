# T3.1 — Mounting the Känguru Tutor into the AuDHS Tutor (proposal, 2026-10-23)

Status: **Saru chose option B (in-process mount) on 2026-10-23.** The AuDHS ADR is drafted in
[`adr-drafts/audhs-0021-kaenguru-in-process-module.md`](adr-drafts/audhs-0021-kaenguru-in-process-module.md);
Saru creates it in AuDHS with `/adr`. Nothing in `~/projects/audhs-tutor` has been changed.
AuDHS requires an ADR for this (its CLAUDE.md: structural changes via `/adr`, which only the owner invokes).

## What the original plan assumed, and what AuDHS actually is

ARCHITECTURE.md §8 assumed "reuse the host app's auth; same local Supabase project". Surveyed AuDHS today:

| Topic | AuDHS Tutor (binding) | Känguru Tutor |
|---|---|---|
| Identity | No login; one owner (`api/deps.py: get_learner` → `get_or_create_owner`) | Supabase Auth ES256 JWT, RLS per user |
| State | SQLite (WAL) + Qdrant, "one container" | Local Supabase: Postgres, Auth, Storage, pg_cron |
| Pedagogy | Explicit explanation by default, Socratic opt-in per session, never silently switch | Socratic by default |
| Learner model | Kernel owns memory (FSRS) and competency | Own mastery ledger + FSRS in `tutor.mastery_ledger` |
| Frontend | React 19, shadcn/ui, TanStack Query, pnpm | React 18, Tailwind 4, npm |

Also: AuDHS has uncommitted work from 2026-10-15 (ask-context proposals); an integration must not touch
those files.

## Options

**A. Sidecar with a token bridge (recommended).** Känguru keeps running as its own service (:8020, its own
Supabase stack); AuDHS works unchanged when it is off.
- AuDHS backend: one thin router `/api/kaenguru/*` that reverse-proxies to `KAENGURU_URL` (SSE passed
  through) and adds `Authorization: Bearer <token>`. The token is the owner's Supabase session, obtained
  server-side by signing in one configured Supabase user (`KAENGURU_EMAIL` / `KAENGURU_PASSWORD` in AuDHS
  config). Shared auth = AuDHS owner ↔ one Supabase user: no second login, no Supabase key in the browser.
- Känguru frontend: `TutorApp` gets a host-auth mode (token comes from the host, no login form, API base =
  the host proxy). AuDHS adds a route `/kaenguru` that renders it (pnpm link to `frontend/src/tutor` or a
  small built package); it works with React 19.
- Pedagogy: the AuDHS route asks per session "Socratic or explicit?" (default explicit, AuDHS rule);
  Känguru gets an explicit delivery mode (one step, then a check question) instead of Socratic.
- Learner model: separate for now; a later task sends Känguru outcomes into AuDHS as competency evidence
  events, so the AuDHS kernel stays the owner of learner state.
- Cost: ~1 AuDHS ADR, 1 router + config keys + tests, 1 frontend route; in Känguru the host-auth mode and the
  explicit mode.

**B. In-process mount (the original plan).** `app.include_router(tutor_router, prefix="/tutor")` inside
AuDHS. AuDHS would then depend on Postgres/Supabase, psycopg, the Anthropic SDK and Känguru's package;
its tests would need the Supabase stack. Contradicts "SQLite + one container" and needs a bigger ADR.
Not recommended.

**C. Link out.** An AuDHS navigation entry that opens the standalone Känguru app (own login). No ADR-level
coupling, no shared auth; it does not meet T3.1's "shared auth".

## Decisions needed from Saru

1. Option A, B or C.
2. Socratic vs explicit inside AuDHS: per-session choice with explicit as default (AuDHS rule) — confirm.
3. Run `/adr` in the AuDHS repo for the chosen option (owner-only); I can draft its text.
