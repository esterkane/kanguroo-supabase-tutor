---
name: socratic-tutor-loop
description: Build and change the tutor's reasoning turn — prompt assembly from prompts/, Claude tool loop (search_docs, web_search, run_lab_sql, ledger), TutorTurn structured output, the output guard, SSE streaming and the FastAPI router. Use for anything that changes what the tutor says or how it decides.
---

# Socratic tutor loop

## Prompt assembly (`backend/tutor/prompt.py`)
Order matters; concatenate with `\n\n---\n\n`:
1. `prompts/kaenguru_master_instructions.md` — persona adapter + full operating manual (do not edit; it is Saru's source of truth).
2. `prompts/tutor_runtime.md` — tool contract, citation format, output schema, safety.
3. `prompts/modes/<mode>.md` — lesson | incident | exam | neutral | rabbit_hole.
4. Dynamic block: session language, persona on/off, learner nickname, today's objective,
   mastery ledger summary (top-10 weakest + last 3 reviewed), active lab + its phase,
   last session's "still wrong" list.
Cache 1–3 with prompt caching (`cache_control` on the static prefix) — this is the bulk of
the tokens and never changes within a session.

## Tool loop (`backend/tutor/orchestrator.py`)
- `anthropic` SDK, streaming, tools from `prompts/tools.md` (JSON schemas live in
  `backend/tutor/tools.py` and must match the markdown one-to-one — a test asserts it).
- Max 6 tool calls per turn, max 2 `web_search`. On the 7th, stop and answer with what
  you have, saying so.
- Tool results are *data*. Wrap web results in `<untrusted_source url=... tier=4 date=...>`.
- The final message must be a `TutorTurn` JSON block after the streamed markdown.
  Parse with `pydantic`; on failure, retry once with the validation error appended; on
  second failure, wrap the raw text as `text` and set `guard_flags=['unstructured']`.

## TutorTurn (see prompts/tutor_output_schema.md)
`speech, text, diagrams[], citations[], next_question, ledger_delta[], mode, lab_action?`
Invariants the guard enforces:
- exactly one `next_question` in lesson/exam/rabbit_hole; may be null only in incident
  mode when the learner asked for the fix directly or in a session-end summary.
- every sentence in `text` that states product behaviour, limits, versions, prices or CLI
  syntax has a citation marker `[n]` resolving to `citations[n]` with `tier` ≤ 3 — or is
  labelled "community (tier 4)" / "unverified".
- `speech` ≤ 60 words, no code, no URLs, no Mermaid, persona voice if persona on.
- no `service_role`/JWT secrets in `text`; destructive SQL only inside a block that starts
  with `> ⚠ Risk:` (the only allowed emoji-like glyph; persona itself uses none).

## Guard (`backend/tutor/guard.py`)
Pure functions over `TutorTurn`; each returns `GuardFinding(code, severity, fix_hint)`.
`severity=block` → the orchestrator sends one repair message to the model with the
findings; `warn` → logged + shown in dev UI. Codes: `NO_QUESTION`, `MULTI_QUESTION`,
`UNCITED_CLAIM`, `SECRET_LEAK`, `DESTRUCTIVE_SQL_UNFLAGGED`, `INCIDENT_MODEL_MISSING`,
`PERSONA_IN_CODE`, `SPEECH_TOO_LONG`, `WEB_SEARCH_UNJUSTIFIED`.

## Modes
- **lesson** (default): 10-step cycle; one question; small steps; predictions before experiments.
- **incident**: fill the incident model progressively (SYMPTOM … CONFIDENCE); no fix before
  reproduction + evidence + hypothesis + test; "reveal fix" command bypasses.
- **exam**: no hints unless asked; score answers into ledger; fresh transfer scenarios.
- **neutral**: persona off; concise; same technical contract.
- **rabbit_hole**: mark "main path / rabbit hole / return point"; descend mechanism by
  mechanism; stop criteria from the manual.

## First turn
Introduce in character (≤ 3 short paragraphs), state the plan (baseline case → macOS
prerequisites → disposable CLI lab → request trace), ask exactly ONE easy scenario
question (GRANT vs RLS, or which Docker-compatible runtime is installed). No setup dump.

## Session end
When the learner says "done/fertig/recap" or after the lab outcome is recorded, emit the
five-heading summary: WHAT I SHOULD NOW UNDERSTAND / WHAT I PROVED IN THE LAB / WHAT I
STILL GOT WRONG / THREE RETRIEVAL QUESTIONS / ONE SUPPORT CASE TO THINK ABOUT NEXT, and
write `ledger_delta` with evidence strings pointing at lab_run ids.

## Router (`backend/tutor/router.py`)
`POST /turn` (SSE: `token`, `tool_call`, `tool_result_summary`, `turn` events),
`GET /session/{id}`, `GET /ledger`, `POST /lab/{slug}/{install|reset|status}`,
`POST /internal/refresh` (token-guarded). JWT verified against the local Supabase JWKS;
`user_id` from `sub`. All DB access for user tables uses a connection with
`set local role authenticated` + `request.jwt.claims`, so RLS is the authority, not the app.
