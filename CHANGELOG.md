# Changelog
- 2026-10-21 scaffold: architecture, decisions, roadmap, CLAUDE.md, TASKS.md, 9 skills, 2 agents,
  prompts (master + runtime + schema + tools + 5 modes), core migration + pgTAP, ingest script
  (+ offline tests), lab DB script, lab 01, curriculum, Makefile.
- 2026-10-21 Phase 0 (T0.1–T0.8): supabase init (CLI 2.121.0, PG 17, pooler on); migration fix — qualify
  pgvector `<=>` as `operator(extensions.<=>)` under `search_path = ''`; generated seed (63 topics, lab 01);
  psql-free scripts (`db.py`, `lab_db.py` with ''-safe auth shim, `lab.py` list/install/reset/check/solve/sync,
  `seed.py`, `smoke.py`); pgTAP 16 tests incl. RLS on every tutor table; `make test-labs` checks each lab
  FAILS broken and PASSES solved; Vite+React+TS+Tailwind shell with vitest; dev ports 8020/5180;
  persona `prompts/persona/kaenguru_persona.yaml` added for T1.4.
