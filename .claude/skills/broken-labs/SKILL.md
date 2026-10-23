---
name: broken-labs
description: Author, install and run intentionally broken Supabase/PostgreSQL labs (RLS, grants, JWT identity, slow policies, locks, long transactions, connection exhaustion, migration drift) in the disposable lab database, plus the lab runner sandbox. Use for labs/<slug>/ and backend/tutor/lab_runner.py.
---

# Broken labs

## Lab anatomy (`labs/<nn>-<slug>/`)
```
README.md      learner-facing scenario: customer report, environment, available evidence. NO solution.
setup.sql      idempotent: create schema <slug>; objects; seed; the deliberate defect
hints.md       ordered hints h1..h5, each one step; the tutor reveals one at a time on "hint"
solution.sql   the fix + verification queries (before/after); tutor reads it, never pastes it unasked
checks.sql     pgTAP tests that PASS only when the defect is fixed (used by exam mode + evals)
lab.yaml       slug, phase (A..M), topics[], difficulty, est_minutes, discriminating_tests[]
```
Register in `supabase/seed.sql` (`insert into tutor.lab ...`) via `scripts/lab.py sync`.

## Design rules
- One root mechanism per lab; red herrings allowed but must be resolvable by evidence.
- The symptom must be reproducible with one command the learner runs as a role
  (`set local role authenticated; set_config('request.jwt.claims', ...)`), and the evidence
  must be collectable with `pg_stat_activity`, `EXPLAIN`, `\dp`, `pg_policies`, SQLSTATE,
  `supabase inspect db ...`.
- Every lab has at least two plausible hypotheses and a *discriminating test* that
  separates them (document them in `lab.yaml`, the tutor uses them to coach).
- Safety: labs run only in database `lab`; `setup.sql` never touches `public`, `auth`
  (other than the shim) or any other lab's schema.

## Lab runner (`backend/tutor/lab_runner.py`)
- Connects to `LAB_DB_URL`; `statement_timeout = 5s` (per lab override up to 30 s for lock labs).
- `run(sql, role='authenticated', claims=None, explain=False, keep_open=False)`:
  `begin; set local role …; set_config(...); savepoint s;` run; capture rows (≤200), SQLSTATE,
  message, detail, hint; if `explain`, run `explain (analyze, buffers, format json)` in a
  rolled-back savepoint; `rollback to s` on error; `commit` only if the lab declares the
  step persistent (`lab.yaml: persistent_steps`).
- Deny-list (regex, case-insensitive): `drop\s+database`, `alter\s+system`, `pg_read_file`,
  `copy .* program`, `create\s+extension\s+(?!pgtap|vector)`, `\\!`. Return a refusal, not
  an exception, so the tutor can explain why.
- Concurrency labs (locks/deadlocks/long transactions) need two sessions: the runner
  supports named sessions (`session='a'|'b'`) kept open for ≤ 120 s, then force-rolled back.
- Every run is logged into `tutor.lab_run.tests[]` with the role, SQL hash, SQLSTATE, ms.
- `scenario_sessions` (lab.yaml) open real sessions at install: default left in an open transaction (a stuck
  job, lab 05); `idle: true` commits so they sit idle (a leaked connection, lab 07); `count: N` opens N;
  `login_role: labNN_x` logs in as a role the lab's setup.sql created NOLOGIN; the runner sets LOGIN and a
  random in-memory password at every install. Only `labNN_*` roles are accepted.
- `reproduce:` (lab.yaml) + `lab_control reproduce`: one fresh connection as the declared role and
  application_name, runs the app's request, closes; returns the real refusal (e.g. 53300) or rows and the
  session settings it got.
- The only role DDL the runner lets through: `alter role labNN_x set|reset idle_session_timeout |
  idle_in_transaction_session_timeout | statement_timeout` (the per-user setting PostgreSQL documents).
- Roles are cluster-wide and the lab DB shares the server with the tutor and Supabase: never exhaust
  `max_connections`; use a role CONNECTION LIMIT instead (lab 07).

## Starter catalogue (Phase 2 T2.3)
| nn | slug | phase | mechanism |
|---|---|---|---|
| 01 | rls-vs-grant | D | SELECT policy correct, table GRANT missing → 42501 before policy runs |
| 02 | wrong-jwt-identity | D | policy uses `auth.uid()`, claims carry `sub` of another user; NULL semantics |
| 03 | slow-rls-policy | H | policy with subquery per row, no index on `user_id` → seq scan; add index + `(select auth.uid())` |
| 04 | missing-index | H | ORDER BY + LIMIT on 2M rows; teach selectivity before indexing |
| 05 | lock-contention | I | session A holds `ACCESS EXCLUSIVE` via DDL in open tx; session B blocks; `inspect db blocking` |
| 06 | long-tx-autovacuum | I | idle-in-transaction prevents dead tuple cleanup; `vacuum-stats` + `n_dead_tup` |
| 07 | connection-exhaustion | J | script opens N connections; `max_connections`; pool mode semantics |
| 08 | migration-drift | G | local migration history ≠ lab DB state; `migration repair` concepts |
