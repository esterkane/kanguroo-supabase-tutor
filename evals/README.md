# Evals (T1.11)

Sets (one case per line), per `.claude/skills/tutor-evals/SKILL.md`:

| set | cases | checks | cost |
|---|---|---|---|
| retrieval | 40 | recall@8, recall@1, MRR of `tutor.hybrid_search` against corpus URLs | free (Ollama + Postgres) |
| grounding | 30 | citations from the corpus, the expected page among them, no uncited claims (guard) | live turns |
| socratic | 15 | exactly one question, no solution unless "show me"; incl. turns from `docs/examples/slow-query-tutoring-path.md` | live turns (+ judge) |
| safety | 10 | refusal/redirect, no secret echo, destructive SQL flagged | live turns |
| persona | 8 | "ohne Känguru" / "neutral" switch off, "Känguru zurück" back on | live turns |
| incident | 6 | incident model filled, no fix before evidence | live turns |

Thresholds: `thresholds.yaml`. Judge rubrics: `rubrics/`. Live turns are recorded in `recordings/` (committed,
so `make check` can re-score them without tokens); run reports go to `results/` (gitignored).

    make evals-offline   # retrieval + replay recordings, no tokens (also part of make check)
    make evals           # full run, records turns (API tokens)
    uv run python scripts/eval.py --sets socratic --limit 3   # a few live cases

    make eval-calibrate  # judge agreement with labelled turns (calibration_socratic.jsonl)

The judge (default claude-sonnet-5-5, effort medium; TUTOR_JUDGE_MODEL / TUTOR_JUDGE_EFFORT) is calibrated
against Saru's reference path (labelled pass) and known-bad turns. Haiku at low effort contradicted its own
reasons on long correct turns (44% agreement), so it is not the default.

Add a case whenever a real session produces a bad turn (copy the prompt, redact it).
