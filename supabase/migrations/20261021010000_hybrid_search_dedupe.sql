-- hybrid_search: collapse hits with identical chunk text.
-- The docs publish many pages under two URLs (docs/guides/troubleshooting/* and kb/troubleshooting/*,
-- auth/row-level-security and database/postgres/row-level-security), so without this the top-k is
-- half duplicates. Candidate pools grow from 30 to 60 to keep enough unique rows after collapsing.
-- docs/guides URLs win ties: the KB rendering of mirrored articles rewrites links to broken /kb/... URLs.

create or replace function tutor.hybrid_search(
  query           text,
  query_embedding extensions.vector(768),
  k               integer default 8,
  source_filter   text[]  default null,
  rrf_k           integer default 60
)
returns table (
  chunk_id     uuid,
  url          text,
  anchor       text,
  heading_path text,
  content      text,
  tier         smallint,
  fetched_at   timestamptz,
  score        double precision
)
language sql
stable
security invoker
set search_path = ''
as $$
  with sem as (
    select c.id, row_number() over (order by c.embedding operator(extensions.<=>) query_embedding) as r
    from tutor.docs_chunk c
    where c.embedding is not null
      and (source_filter is null or c.meta->>'product' = any(source_filter))
    order by c.embedding operator(extensions.<=>) query_embedding
    limit 60
  ),
  lex as (
    select c.id, row_number() over (order by ts_rank_cd(c.fts, q) desc) as r
    from tutor.docs_chunk c,
         websearch_to_tsquery('english', query) q
    where c.fts @@ q
      and (source_filter is null or c.meta->>'product' = any(source_filter))
    order by ts_rank_cd(c.fts, q) desc
    limit 60
  ),
  ids as (select id from sem union select id from lex),
  scored as (
    select
      c.id, s.url, c.anchor, c.heading_path, c.content, s.tier, s.fetched_at, c.content_hash,
      coalesce(1.0 / (rrf_k + sem.r), 0) + coalesce(1.0 / (rrf_k + lex.r), 0) as score
    from ids
    join tutor.docs_chunk c on c.id = ids.id
    join tutor.docs_source s on s.id = c.source_id
    left join sem on sem.id = ids.id
    left join lex on lex.id = ids.id
    where s.status = 'active'
  ),
  -- Copies of one text get adjacent ranks, so the group keeps its best score and the URL is
  -- chosen by the docs/guides rule alone (not by which copy happened to rank first).
  uniq as (
    select distinct on (content_hash)
      id, url, anchor, heading_path, content, tier, fetched_at,
      max(score) over (partition by content_hash) as best
    from scored
    order by content_hash, (url like '%/docs/guides/%') desc, url
  )
  select id, url, anchor, heading_path, content, tier, fetched_at, best
  from uniq
  order by best desc
  limit k;
$$;

comment on function tutor.hybrid_search is
  'RRF fusion of HNSW cosine search and FTS over the official Supabase corpus, one row per distinct chunk text. Used by the tutor''s search_docs tool and as a teaching example for EXPLAIN.';
