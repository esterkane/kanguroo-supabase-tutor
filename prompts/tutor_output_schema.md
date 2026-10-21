# TutorTurn schema

Pydantic model lives in `backend/tutor/schemas.py`; this is the human-readable contract.

```json
{
  "mode": "lesson | incident | exam | neutral | rabbit_hole",
  "language": "de | en",
  "persona_on": true,
  "speech": "Kleinkünstler, GRANT ist der Haustürschlüssel, die Policy das Kühlschrankfach. Welche Kontrolle prüfst du zuerst bei SQLSTATE 42501?",
  "text": "<the full Markdown shown to the learner, identical to the streamed part>",
  "diagrams": [
    { "id": "d1", "kind": "sequenceDiagram | flowchart | erDiagram | xychart-beta", "title": "Request flow", "code": "sequenceDiagram\n  participant C as client\n  ..." }
  ],
  "citations": [
    { "n": 1, "url": "https://supabase.com/docs/guides/database/postgres/row-level-security#...", "title": "Row Level Security", "tier": 1, "fetched_at": "2026-10-21T18:02:11Z" }
  ],
  "next_question": "Which control would you inspect first when the database returns SQLSTATE 42501?",
  "path": { "state": "main | rabbit_hole", "depth": 0, "return_point": "request flow lesson, step 3" },
  "ledger_delta": [
    { "topic": "rls-vs-grants", "score": 2, "evidence": "predicted 42501 came from grant layer before running lab_run 7c1…" }
  ],
  "lab_action": { "slug": "01-rls-vs-grant", "action": "install | reset | check | hint" },
  "incident": {
    "symptom": "...", "expected": "...", "scope": "...", "timeline": "...", "environment": "...",
    "evidence": ["..."], "hypotheses": [{"h": "...", "rank": 1, "test": "..."}],
    "root_cause": null, "mitigation": null, "permanent_fix": null, "prevention": null, "confidence": null
  },
  "session_end": {
    "understand": ["..."], "proved": ["..."], "still_wrong": ["..."],
    "retrieval_questions": ["...", "...", "..."], "next_case": "..."
  }
}
```

Field rules
- `text` required; `speech` required; `next_question` required unless `mode == incident`
  and the learner asked for the fix, or `session_end` is present.
- `citations[].n` must be the set of `[n]` markers used in `text`.
- `incident` only in incident mode; fill progressively, keep `null` for unknowns.
- `session_end` only once per session, on `done/fertig/recap` or after lab outcome.
- Unknown fields are rejected (`extra = "forbid"`).
