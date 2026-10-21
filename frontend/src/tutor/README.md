# frontend/src/tutor

Exports `<TutorApp supabase={client} apiBase="/tutor" />`. Standalone `frontend/src/main.tsx` creates the
Supabase client from `frontend/.env.local` (public URL + publishable key, written by `make env`); the AuDHS
Tutor mounts the same component and passes its own client.

  TutorApp.tsx              auth gate, session resume/new, layout: chat (left), sidebar tabs (right)
  api.ts / sse.ts           typed client for /session, /turn (SSE over POST), /ledger, /labs, /lab/*
  chatReducer.ts            pure chat state: tokens, tool activity, guard rewrites, final TutorTurn
  chat/ChatPanel.tsx        transcript + live stream + composer (Enter sends, Shift+Enter newline)
  chat/TurnView.tsx         Markdown (GFM), diagrams, citations with tier labels, guard flags
  chat/MermaidBlock.tsx     lazy mermaid, securityLevel strict, code fallback, copy
  lab/LabConsole.tsx        learner SQL in the session's lab sandbox (role, JWT sub, EXPLAIN, persist)
  lab/PlanTree.tsx          EXPLAIN JSON as a tree; >10x row misestimates highlighted
  sidebar/LessonSidebar.tsx objective, mode, path tracker, mode command buttons
  sidebar/LabsPanel.tsx     install / status / check per lab
  sidebar/Ledger.tsx        0–5 bars, weakest first, "review" sends `recap <topic>`
  i18n.ts                   learner-facing strings (de default, en)
  types.ts                  mirrors backend/tutor/schemas.py

Voice (Web Speech, `speech` track) is T2.1. Style: Tailwind, Kibana-like density, dark, no emoji.
