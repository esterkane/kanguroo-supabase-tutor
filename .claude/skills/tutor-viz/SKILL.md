---
name: tutor-viz
description: Render the tutor's visual explanations — Mermaid (sequence, flowchart, erDiagram, xychart), comparison tables, EXPLAIN plan trees, and the lesson sidebar (main path / rabbit hole / return point, ledger). Use for frontend/src/tutor/* UI work.
---

# Visualisation

## Mermaid
- `mermaid` npm package, `securityLevel: 'strict'`, theme matched to the Tailwind dark/light
  tokens. Render each `TutorTurn.diagrams[i].code` in an isolated component; on parse error
  show the code fence and a one-line "diagram failed to render" (never crash the turn).
- The model is told (runtime prompt) which diagram types are allowed and the size limit
  (≤ 40 nodes). Prefer `sequenceDiagram` for request flows, `flowchart TD` for decision
  trees, `erDiagram` for schema, `xychart-beta` for before/after numbers.
- Export: "copy as Mermaid" and "download SVG".

## Tables
Comparison tables come as Markdown in `text`; render with the shared Markdown component
(GFM). Monospace for identifiers.

## EXPLAIN plans
`run_lab_sql(explain=true)` returns `format json`. Render as a collapsible tree:
node type, est. rows vs actual rows (highlight >10× misestimates), buffers hit/read,
time. Keep the raw JSON available. This is the single most important teaching visual for
Phase H — make it good.

## Lesson sidebar
- Objective of the session; current phase (A..M); current lab + step.
- Path tracker: **main path** · **rabbit hole** (depth) · **return point** — set from
  `TutorTurn.mode` and the model's markers.
- Mastery ledger mini-view (0–5 bars), weakest-first, with "review now" button that sends
  `recap <topic>`.
- Mode switches as buttons that send the literal commands: hint, show me, skip, neutral,
  rabbit hole, recap, exam, slower, faster, ohne Känguru.

## Style
Kibana-like density: compact spacing, monospace where it matters, no emoji, no
exclamation-mark UI copy. Dark mode default. Everything keyboard-reachable.
