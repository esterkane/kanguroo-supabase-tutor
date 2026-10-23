# Architecture decision records

Short form. Revisit when the "Revisit when" condition triggers.

## ADR-001 Vector store: pgvector in Supabase (not Qdrant)

- **Decision:** `docs_chunk.embedding vector(768)` + HNSW, hybrid with Postgres FTS.
- **Why:** The product teaches Supabase; running the corpus in the same Postgres makes
  `EXPLAIN` on your own search, HNSW parameters, RLS on chunks and `pg_cron` refresh
  into lessons. One fewer container. Corpus size (llms-full + sub-files + guides)
  is well under 100k chunks — comfortably in pgvector territory.
- **Trade-off:** Qdrant has better filtering ergonomics and is the preferred store in
  the AuDHS Tutor for the Udemy corpus. Keep the search tool behind an interface
  (`backend/tutor/retrieval.py: Retriever`) so a `QdrantRetriever` can be added for
  the host app's corpus without changing the tutor.
- **Revisit when:** >500k chunks, or when the AuDHS host needs one unified store.

## ADR-002 Orchestration: FastAPI, not Edge Functions

- **Decision:** The tool loop runs in FastAPI (`backend/tutor`).
- **Why:** Matches the AuDHS Tutor backend, Python ecosystem for evals/reranking/voice,
  long-running SSE streams and the lab runner's SQL sandbox are easier outside the
  Edge runtime's wall-clock limits. Edge Functions remain a *teaching topic* and get one
  demo function (`supabase/functions/hello-grounded`) for Phase F lessons.
- **Revisit when:** moving to hosted and wanting zero-ops backend.

## ADR-003 Embeddings: local `nomic-embed-text` (Ollama), API as switch

- **Decision:** `EMBEDDINGS_PROVIDER=ollama|openai` with a fixed dimension per corpus
  version; changing provider means re-ingesting (`docs_source.embedding_model`).
- **Why:** Free, fast on M4 Pro, good enough for docs retrieval; hybrid FTS covers
  exact identifiers (`SQLSTATE 42501`, `statement_timeout`) where embeddings are weak.

## ADR-004 Tutor model: Claude via API, with cheap pre-steps local

- **Decision:** One API call per tutor turn with tools; summarisation of long pasted
  logs and the "did the learner answer the question?" classifier can run on a local
  model (Ollama) to keep API tokens low.
- **Revisit when:** a local model passes the eval suite in `evals/` at ≥90% of API quality.

## ADR-005 Voice: browser Web Speech API first

- **Decision:** STT/TTS in the browser; `speech` field separate from `text`.
- **Why:** zero cost, zero keys, works offline. A server voice (Piper/Kokoro) is an
  additive Phase 2 feature behind `TUTOR_TTS=browser|server`.
- **Addendum 2026-10-23 (R11):** German server voice = Piper `de_DE-thorsten-high`. Browser German voices on
  macOS are robotic unless a Premium voice is installed. Piper 1.8 is GPL-3.0, so it runs as its own process
  (`uvx`, Piper's HTTP server, `make tts`) and the backend talks HTTP to it; it is not a dependency of this
  repo. The endpoint takes a `turn_id`, never free text, so only a stored `speech` track is voiced. MP3 via
  ffmpeg is cached in the private bucket `tutor-audio` and played via a 1 h signed URL. English stays on the
  browser voice (or Kokoro, R9).

## ADR-006 Structured tutor output

- **Decision:** The model must return `TutorTurn` JSON (schema in
  `prompts/tutor_output_schema.md`), streamed as text first then a final JSON block.
- **Why:** Exactly-one-question, citations, diagrams, ledger deltas and the speech
  track all need to be machine-checkable by the guard and by evals.

## ADR-007 Web search is gated

- **Decision:** `web_search` is only allowed for the categories in the master
  instructions ("CURRENT INFORMATION") or when `search_docs` returns no hit ≥ threshold.
  Every result carries `tier` and a date; the model must label community evidence.

## ADR-008 Lab execution runs only in a disposable lab database

- **Decision:** `run_lab_sql` connects to database `lab`, never to `postgres`, never to
  a hosted project. Deny-list + transaction + SAVEPOINT. The learner's own projects are
  reached only through the learner pasting outputs.

## ADR-009 Standalone and sub-module from day one

- **Decision:** `backend/tutor` is a package exposing `router` and `TutorService`;
  `frontend/src/tutor` exports `<TutorApp/>`. No imports from the host app.

## ADR-010 Scripts talk to Postgres via psycopg, not psql

- **Decision:** lab DB setup, lab install/check, seed and smoke are Python (`scripts/*.py`, psycopg 3).
  `scripts/lab_db.sh` is a wrapper only.
- **Why:** `psql` is not installed on the target Mac and the backend already depends on psycopg; one
  fewer prerequisite. `supabase test db` still runs pgTAP for the main schema.
- **Constraint:** `lab.py solve` splits `solution.sql` on a `;` at line end and continues past errors
  (the "before" query fails on purpose), so lab SQL keeps one statement terminator per line end.

## ADR-011 Real datasets live in the lab database; synthetic additions are labelled

- **Decision:** Hands-on lessons use real data (first: Olist e-commerce, `make olist`) imported into the
  disposable `lab` DB, so `run_lab_sql` and the learner see the same real rows, plans and errors. Anything
  the dataset lacks (login identities, production-like volume) is added synthetically and said so in the
  lab README and table comments (`olist.app_users`, `lab04.orders` growth).
- **Why:** Saru wants lessons testable on real data and real system conditions, with no simulated outputs;
  the lab DB already has the sandbox (roles, claims, timeouts, deny-list).
- **Constraint:** Auth/PostgREST/Storage/Realtime/Edge Function lessons need the main local stack; giving the
  runner a second target is a separate decision (TASKS O7).
