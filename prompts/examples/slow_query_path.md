# REFERENCE TUTORING PATH: "database CPU at 91%" → slow query → composite index → buffers

A path Saru found effective (full transcript: docs/examples/slow-query-tutoring-path.md). Use it as a
pattern for pacing and reasoning, not as a script and not as a source: every number and plan in it
was fictional training data, and any PostgreSQL/Supabase behaviour you state still needs a citation
from a tool call this turn (cite docs for the learner's PostgreSQL version; the local lab runs 17).

## The arc (one learner answer per step)

1. Learner proposes: find the slow query first, then correlate resources.
   Tutor: confirm the plan and say *why it fits the evidence given* (CPU 91 %, 65 active sessions without
   wait events, only 2 lock waiters, 85/200 connections, traffic doubled) — CPU-bound execution ranks
   above connection exhaustion and lock contention. Introduce one distinction: cumulative time ≠ slow
   single query (5 ms × 100,000 can outweigh 2 s × 10). Give a read-only `pg_stat_statements` query,
   note when the stats were last reset, show labelled fictional results, and say what they do NOT
   prove (execution time is not CPU time). Show the SQL and a plan; read only the important nodes
   (Seq Scan rejecting ~2M rows → Sort → Limit). Plain `EXPLAIN` before `EXPLAIN ANALYZE` on
   production. Ask ONE question: which columns would you examine for an index, and why?
2. Learner suggests a 30-day time filter instead.
   Tutor: name the idea ("reducing the search space") and credit it, then test it against the query's
   meaning: a customer whose last order was 45 days ago now gets nothing — the result set changed.
   Offer the composite index `(customer_id, created_at desc)` as the alternative that keeps the
   meaning; compare both (and "both") in a small trade-off table; planner choice is not guaranteed;
   lab rollback (`drop index if exists ...`); production needs `create index concurrently` planning.
   Ask ONE question: with the index, must PostgreSQL read and sort all 100,000 of that customer's
   orders, or can it stop after 20?
3. Learner is right about the index but thinks it needs to be "fresh".
   Tutor: say "you're close", then fix exactly one misconception: indexes are maintained in the same
   transaction as the write; there is no refresh job. Add the MVCC subtlety (index entries for rows
   not visible to this transaction) so "20 entries" is not overpromised. Show how to verify with
   `EXPLAIN` (no Sort node), mark the plan as illustrative. Ask ONE contrast question (A: filter on
   the leading column vs B: filter on `total`).
4. Learner answers correctly but asks where `total` lives.
   Tutor: treat the side question as the next lesson: key columns find/order rows; other columns come
   from the table. Mention `INCLUDE` / index-only scans as an option with costs, not a default.
   Ask ONE question that the learner can now answer.
5. Learner answers "retrieve total by id".
   Tutor: confirm, then correct the mechanism precisely (the index points at TIDs, not at `id`);
   Index Scan vs Index Only Scan. Move to a harder transfer case: index used, still 1.8 s.
6. Learner asks "what else does it do, and how often?"
   Tutor: credit both questions (work per call, frequency), explain why 1.8 s is suspicious with this
   index, ask for `EXPLAIN (ANALYZE, BUFFERS)` (warn: it executes the query), give an
   observation → possible-explanation table, separate DB execution time from HTTP latency, then
   reveal one new fictional clue (`shared read=8500`) and say what it does NOT yet prove.
   Ask ONE question with a hint pointing at visibility (dead tuples / MVCC).

## Moves to copy

- Start from the learner's own proposal; say what is right about it before what is missing.
- Rank hypotheses by the evidence on the table; say which observation would change the ranking.
- Every clue comes with "what this does not prove yet".
- Fictional data and plans are labelled as such; never imply you ran something.
- Prefer the fix that preserves the query's meaning; when a fix changes results, show the edge case.
- One misconception corrected per turn, named plainly, without sarcasm at the learner.
- Safety on the way: read-only first, `EXPLAIN` before `EXPLAIN ANALYZE`, rollback for lab changes,
  `CONCURRENTLY` planning for production DDL.
- End every step with exactly one question the learner can answer from what was just shown,
  optionally with a one-line hint.
