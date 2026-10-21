# frontend/src/tutor

Exports `<TutorApp supabase={client} apiBase="/tutor" />`. Standalone `frontend/src/main.tsx`
renders it at `/`; the AuDHS Tutor adds a route `/tutor` and passes its own Supabase client.

Planned files (T1.9, T2.1):
  TutorApp.tsx            layout: chat (left), lesson sidebar (right)
  chat/ChatPanel.tsx      SSE consumer, Markdown + Mermaid blocks, citations footnotes
  chat/MermaidBlock.tsx   strict mermaid render with code-fence fallback
  chat/PlanTree.tsx       EXPLAIN json → tree
  sidebar/LessonSidebar.tsx  objective, phase, lab step, path tracker, mode buttons
  sidebar/Ledger.tsx      0–5 bars, weakest first
  voice/useSpeech.ts      Web Speech STT/TTS hooks (feature-detected)
  api.ts                  typed client for /turn, /session, /ledger, /lab
  types.ts                TutorTurn mirrors backend/tutor/schemas.py
Style: Tailwind, Kibana-like density, dark default, no emoji.
