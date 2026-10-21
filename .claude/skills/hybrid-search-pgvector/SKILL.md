---
name: hybrid-search-pgvector
description: Implement and tune the tutor's hybrid retrieval in Postgres — pgvector HNSW cosine + full-text search fused with RRF — plus the Python Retriever interface and EXPLAIN-based tuning. Use for tutor.hybrid_search, indexes, search quality tests.
---

# Hybrid search (pgvector + FTS, RRF)

## SQL function (authoritative version in the core migration)
`tutor.hybrid_search(query text, query_embedding vector(768), k int default 8,
source_filter text[] default null, rrf_k int default 60)`

Shape:
```sql
with sem as (
  select id, row_number() over (order by embedding <=> query_embedding) as r
  from tutor.docs_chunk
  where (source_filter is null or meta->>'product' = any(source_filter))
  order by embedding <=> query_embedding limit 30
), lex as (
  select id, row_number() over (order by ts_rank_cd(fts, q) desc) as r
  from tutor.docs_chunk, websearch_to_tsquery('english', query) q
  where fts @@ q and (source_filter is null or meta->>'product' = any(source_filter))
  limit 30
)
select c.id, ... , coalesce(1.0/(rrf_k+sem.r),0)+coalesce(1.0/(rrf_k+lex.r),0) as score
from (select id from sem union select id from lex) ids
join tutor.docs_chunk c using (id)
left join sem using (id) left join lex using (id)
order by score desc limit k;
```
Declared `language sql stable security invoker set search_path = ''`.

## Indexes
- `create index on tutor.docs_chunk using hnsw (embedding vector_cosine_ops) with (m=16, ef_construction=64);`
- `create index on tutor.docs_chunk using gin (fts);`
- `fts` is a generated column: `to_tsvector('english', heading_path || ' ' || content)`.
- After bulk ingest: `analyze`. `hnsw.ef_search = 100` and `hnsw.iterative_scan = relaxed_order`
  are pinned on the function (`alter function ... set`), not per session. A function-level
  `set hnsw.*` needs pgvector's library loaded first (`select '[1]'::extensions.vector;`), or
  the postgres role gets 42501 on the placeholder parameter.
- Filtered HNSW pitfall (taught in Phase H): the index returns ef_search rows and the WHERE filter
  runs afterwards, so a selective filter empties the semantic side. Regression test:
  `supabase/tests/003_hybrid_search_filtered.sql`.

## Python side (`backend/tutor/retrieval.py`)
```python
class Retriever(Protocol):
    async def search(self, query: str, k: int = 8, products: list[str] | None = None) -> list[Chunk]: ...
```
`PgHybridRetriever` embeds the query (with the nomic `search_query:` prefix when using
nomic), calls the function with `psycopg`, and returns `Chunk(url, anchor, heading_path,
content, tier, fetched_at, score)`. Optional `Reranker` stage (bge-reranker-v2-m3 via
Ollama/FlagEmbedding) over top 30 → 8; off by default, on with `RERANK=1`.

## Quality tests (`backend/tests/test_retrieval.py`)
- Fixture: 3 handmade chunks (RLS 42501, `statement_timeout`, Supavisor transaction mode).
- Exact identifier queries (`42501`, `statement_timeout`) must rank the lexical hit first.
- Paraphrase queries ("why does my insert say permission denied") must hit the RLS chunk top-3.
- `evals/retrieval.jsonl`: 40 query→expected-url pairs; report recall@8 and MRR; threshold 0.85 / 0.6.

## Teaching hooks
The tutor uses *its own* search as a lesson: `explain (analyze, buffers)` on
`hybrid_search` shows an HNSW index scan vs seq scan, and raising `k` or dropping the
GIN index makes the plan change visibly. Keep the function readable for that reason.
