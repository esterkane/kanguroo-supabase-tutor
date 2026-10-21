# REFERENCE TUTORING PATH: building the support lab on a real dataset (Olist e-commerce)

A plan Saru found effective (full text: docs/examples/support-lab-olist-plan.md). Use it for pacing and
structure when the learner wants to build or extend their lab; it is not a source. Cite product facts
from search_docs this turn (verified 2026-10-21: Node.js 20+ for the npm/npx CLI, OrbStack recommended on
macOS, `--network-id local-network` with a 127.0.0.1 host binding for untrusted networks).

## What this installation already has (do not re-teach it as missing)

- The local stack runs via `make up`; the learner does not need a second project to start.
- The disposable `lab` database is where datasets and broken labs live; `run_lab_sql` can query it, so
  evidence comes from real queries. Olist goes into schema `olist` (raw `olist_staging`) via
  `make olist` once the learner has downloaded the CSVs into `data/olist/` (Kaggle needs their login).
- `psql` is not installed on this Mac; imports use the project's script, not `\copy`.
- Storage, Realtime and Edge Function incidents need the full local stack, not the `lab` database.
- Hosted projects: the learner links and pushes; you never run CLI commands against them.

## The arc

1. Goal first: "learn what a Support Engineer sees when something goes wrong", not "build an app".
2. Local vs hosted as a comparison table; recommend ~80 % local, a separate hosted dev project only for
   cloud-only behaviour (metrics, logs, network). Destructive experiments stay local.
3. Prerequisites as evidence, not assumptions: one batch of read-only checks (`sw_vers`, `uname -m`,
   `node --version`, `docker info` — `info`, because the CLI can exist while the engine is down), each
   with "what we want to learn". Never claim what the machine has before the learner pastes output.
4. Choose the dataset by the incidents it enables (relational depth → joins, indexes, RLS mapping), name
   the alternatives and why they come second.
5. Two-stage import: raw text staging (accept messy rows), then typed tables with keys and indexes via
   migrations. Verify with counts, status distribution and missing values — data quality is evidence too.
6. Map every lab to "deliberate failure → what you learn" (joins duplicating revenue, missing composite
   index, repeated queries in pg_stat_statements, open transaction holding locks, RLS/JWT, migration
   drift, pooler exhaustion, Storage, Realtime, Edge Functions, dead tuples, recovery).
7. Be explicit about what the dataset lacks (no Auth users, no JWT identities) and create fictional
   users + a mapping table instead of pretending.
8. Every destructive or state-changing step carries its warning and rollback (`supabase stop` vs
   `--no-backup`, `db reset` discards local changes, `db push --dry-run` before `db push`).
9. End with one small checkpoint the learner can do now and paste back; promise "no simulated outputs
   once the lab is operational".
