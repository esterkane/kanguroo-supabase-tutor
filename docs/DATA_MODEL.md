# Data model

Schema `tutor` in the local Supabase project. The authoritative DDL is
`supabase/migrations/20261021000000_tutor_core.sql`; this file explains intent.

```mermaid
erDiagram
  docs_source ||--o{ docs_chunk : has
  session ||--o{ turn : has
  turn ||--o{ citation : has
  session ||--o{ lab_run : has
  lab ||--o{ lab_run : instantiates
  mastery_ledger }o--|| topic : scores

  docs_source {
    uuid id PK
    text url UK
    text tier "1 supabase | 2 github | 3 postgres | 4 community"
    text content_hash
    timestamptz fetched_at
    text status
  }
  docs_chunk {
    uuid id PK
    uuid source_id FK
    text heading_path "H1 > H2 > H3"
    text anchor
    int  ord
    text content
    tsvector fts "generated"
    vector embedding "768"
    jsonb meta
  }
  topic {
    text slug PK
    text phase "A..M"
    text title
  }
  mastery_ledger {
    uuid user_id
    text topic_slug FK
    int score "0..5"
    text evidence
    timestamptz last_reviewed
    timestamptz next_review
  }
  session {
    uuid id PK
    uuid user_id
    text objective
    text mode "lesson|incident|exam|neutral|rabbit_hole"
    bool persona_on
    text language "de|en"
    timestamptz started_at
  }
  turn {
    uuid id PK
    uuid session_id FK
    text role "user|assistant|tool"
    text content
    jsonb tutor_turn "structured output"
    int  input_tokens
    int  output_tokens
    timestamptz created_at
  }
  citation {
    uuid id PK
    uuid turn_id FK
    text url
    text tier
    timestamptz fetched_at
    text quote_hash
  }
  lab {
    text slug PK
    text phase
    text title
    text setup_path
    text difficulty
  }
  lab_run {
    uuid id PK
    uuid session_id FK
    text lab_slug FK
    jsonb hypotheses
    jsonb tests
    text outcome
    timestamptz started_at
    timestamptz finished_at
  }
```

## Search

`tutor.hybrid_search(query text, query_embedding vector, k int, source_filter text[])`
returns chunks ranked by Reciprocal Rank Fusion of

- cosine similarity on `embedding` (HNSW index, `vector_cosine_ops`), and
- `ts_rank_cd(fts, websearch_to_tsquery('english', query))` (GIN index).

Returned columns: `chunk_id, url, anchor, heading_path, content, tier, fetched_at, score`.
The tool layer builds the citation URL as `url || '#' || anchor` when an anchor exists.

## RLS

- `docs_*`, `topic`, `lab`: readable by `authenticated` and `anon` (public corpus),
  writable only by `service_role` (ingest).
- `session`, `turn`, `citation`, `lab_run`, `mastery_ledger`: `user_id = (select auth.uid())`
  for all four operations; FastAPI uses the user's JWT for these tables, not `service_role`.
- Every policy predicate has a supporting index (`user_id`), which the tutor itself uses as a teaching example.

## Lab database

A second local database `lab` (created by `supabase/seed.sql` via `dblink`/`\c` is not
possible in seed; instead `scripts/lab_db.sh` creates it with `psql` using the CLI's
connection string). Each lab in `labs/<slug>/setup.sql` creates its objects inside a
schema named after the lab, so `DROP SCHEMA <lab> CASCADE` resets one lab without
touching the others. Roles `anon`, `authenticated`, `service_role` exist in the lab DB
exactly as in a Supabase project so grant/RLS behaviour matches.
