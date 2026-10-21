-- Känguru Tutor core schema
-- Local-only Supabase project. Reviewed by .claude/agents/db-reviewer before changes.

create extension if not exists vector with schema extensions;
create extension if not exists pg_cron;
create extension if not exists pgtap with schema extensions;

create schema if not exists tutor;
grant usage on schema tutor to anon, authenticated, service_role;

-- ---------------------------------------------------------------------------
-- Corpus
-- ---------------------------------------------------------------------------
create table if not exists tutor.docs_source (
  id               uuid primary key default gen_random_uuid(),
  url              text not null unique,
  tier             smallint not null check (tier between 1 and 4),
  product          text not null default 'other',
  content_hash     text,
  etag             text,
  embedding_model  text,
  corpus_version   integer not null default 1,
  status           text not null default 'active' check (status in ('active','retired','failed')),
  fetched_at       timestamptz,
  created_at       timestamptz not null default now()
);

create table if not exists tutor.docs_chunk (
  id            uuid primary key default gen_random_uuid(),
  source_id     uuid not null references tutor.docs_source(id) on delete cascade,
  ord           integer not null,
  heading_path  text not null default '',
  anchor        text,
  content       text not null,
  content_hash  text not null,
  meta          jsonb not null default '{}'::jsonb,
  fts           tsvector generated always as
                (to_tsvector('english', coalesce(heading_path,'') || ' ' || content)) stored,
  embedding     extensions.vector(768),
  unique (source_id, ord)
);

create index if not exists docs_chunk_fts_idx       on tutor.docs_chunk using gin (fts);
create index if not exists docs_chunk_embedding_idx on tutor.docs_chunk
  using hnsw (embedding extensions.vector_cosine_ops) with (m = 16, ef_construction = 64);
create index if not exists docs_chunk_product_idx   on tutor.docs_chunk ((meta->>'product'));
create index if not exists docs_chunk_hash_idx      on tutor.docs_chunk (content_hash);

-- ---------------------------------------------------------------------------
-- Curriculum + mastery
-- ---------------------------------------------------------------------------
create table if not exists tutor.topic (
  slug   text primary key,
  phase  char(1) not null check (phase between 'A' and 'M'),
  title  text not null,
  ord    integer not null default 0
);

create table if not exists tutor.mastery_ledger (
  user_id       uuid not null default auth.uid(),
  topic_slug    text not null references tutor.topic(slug),
  score         smallint not null default 0 check (score between 0 and 5),
  evidence      text,
  last_reviewed timestamptz not null default now(),
  next_review   timestamptz,
  primary key (user_id, topic_slug)
);

-- ---------------------------------------------------------------------------
-- Sessions and turns
-- ---------------------------------------------------------------------------
create table if not exists tutor.session (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null default auth.uid(),
  objective   text,
  mode        text not null default 'lesson'
              check (mode in ('lesson','incident','exam','neutral','rabbit_hole')),
  persona_on  boolean not null default true,
  language    text not null default 'de' check (language in ('de','en')),
  started_at  timestamptz not null default now(),
  ended_at    timestamptz
);
create index if not exists session_user_idx on tutor.session (user_id, started_at desc);

create table if not exists tutor.turn (
  id            uuid primary key default gen_random_uuid(),
  session_id    uuid not null references tutor.session(id) on delete cascade,
  user_id       uuid not null default auth.uid(),
  role          text not null check (role in ('user','assistant','tool')),
  content       text not null,
  tutor_turn    jsonb,
  input_mode    text not null default 'text' check (input_mode in ('text','voice')),
  input_tokens  integer,
  output_tokens integer,
  created_at    timestamptz not null default now()
);
create index if not exists turn_session_idx on tutor.turn (session_id, created_at);
create index if not exists turn_user_idx    on tutor.turn (user_id);

create table if not exists tutor.citation (
  id         uuid primary key default gen_random_uuid(),
  turn_id    uuid not null references tutor.turn(id) on delete cascade,
  user_id    uuid not null default auth.uid(),
  n          integer not null,
  url        text not null,
  title      text,
  tier       smallint not null check (tier between 1 and 4),
  fetched_at timestamptz
);
create index if not exists citation_turn_idx on tutor.citation (turn_id);
create index if not exists citation_user_idx on tutor.citation (user_id);

-- ---------------------------------------------------------------------------
-- Labs
-- ---------------------------------------------------------------------------
create table if not exists tutor.lab (
  slug        text primary key,
  phase       char(1) not null,
  title       text not null,
  difficulty  text not null default 'medium',
  est_minutes integer,
  topics      text[] not null default '{}',
  setup_path  text not null
);

create table if not exists tutor.lab_run (
  id          uuid primary key default gen_random_uuid(),
  session_id  uuid not null references tutor.session(id) on delete cascade,
  user_id     uuid not null default auth.uid(),
  lab_slug    text not null references tutor.lab(slug),
  hypotheses  jsonb not null default '[]'::jsonb,
  tests       jsonb not null default '[]'::jsonb,
  hints_used  integer not null default 0,
  outcome     text check (outcome in ('solved','abandoned','revealed')),
  started_at  timestamptz not null default now(),
  finished_at timestamptz
);
create index if not exists lab_run_session_idx on tutor.lab_run (session_id);
create index if not exists lab_run_user_idx    on tutor.lab_run (user_id);

-- ---------------------------------------------------------------------------
-- Hybrid search: RRF of cosine (HNSW) and full-text (GIN)
-- ---------------------------------------------------------------------------
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
    limit 30
  ),
  lex as (
    select c.id, row_number() over (order by ts_rank_cd(c.fts, q) desc) as r
    from tutor.docs_chunk c,
         websearch_to_tsquery('english', query) q
    where c.fts @@ q
      and (source_filter is null or c.meta->>'product' = any(source_filter))
    order by ts_rank_cd(c.fts, q) desc
    limit 30
  ),
  ids as (select id from sem union select id from lex)
  select
    c.id,
    s.url,
    c.anchor,
    c.heading_path,
    c.content,
    s.tier,
    s.fetched_at,
    coalesce(1.0 / (rrf_k + sem.r), 0) + coalesce(1.0 / (rrf_k + lex.r), 0) as score
  from ids
  join tutor.docs_chunk c on c.id = ids.id
  join tutor.docs_source s on s.id = c.source_id
  left join sem on sem.id = ids.id
  left join lex on lex.id = ids.id
  where s.status = 'active'
  order by score desc
  limit k;
$$;

-- ---------------------------------------------------------------------------
-- Grants
-- ---------------------------------------------------------------------------
grant select on tutor.docs_source, tutor.docs_chunk, tutor.topic, tutor.lab to anon, authenticated;
grant all on tutor.docs_source, tutor.docs_chunk, tutor.topic, tutor.lab to service_role;

grant select, insert, update, delete on tutor.session, tutor.turn, tutor.citation,
  tutor.lab_run, tutor.mastery_ledger to authenticated;
grant all on tutor.session, tutor.turn, tutor.citation, tutor.lab_run, tutor.mastery_ledger to service_role;

grant execute on function tutor.hybrid_search(text, extensions.vector, integer, text[], integer)
  to anon, authenticated, service_role;

-- ---------------------------------------------------------------------------
-- RLS
-- ---------------------------------------------------------------------------
alter table tutor.docs_source   enable row level security;
alter table tutor.docs_chunk    enable row level security;
alter table tutor.topic         enable row level security;
alter table tutor.lab           enable row level security;
alter table tutor.session       enable row level security;
alter table tutor.turn          enable row level security;
alter table tutor.citation      enable row level security;
alter table tutor.lab_run       enable row level security;
alter table tutor.mastery_ledger enable row level security;

-- Public corpus: readable by everyone, writable only by service_role (ingest).
create policy docs_source_read on tutor.docs_source for select to anon, authenticated using (true);
create policy docs_chunk_read  on tutor.docs_chunk  for select to anon, authenticated using (true);
create policy topic_read       on tutor.topic       for select to anon, authenticated using (true);
create policy lab_read         on tutor.lab         for select to anon, authenticated using (true);

-- Per-user tables: owner-only for all four operations.
create policy session_owner_select on tutor.session for select to authenticated using ((select auth.uid()) = user_id);
create policy session_owner_insert on tutor.session for insert to authenticated with check ((select auth.uid()) = user_id);
create policy session_owner_update on tutor.session for update to authenticated using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy session_owner_delete on tutor.session for delete to authenticated using ((select auth.uid()) = user_id);

create policy turn_owner_select on tutor.turn for select to authenticated using ((select auth.uid()) = user_id);
create policy turn_owner_insert on tutor.turn for insert to authenticated with check ((select auth.uid()) = user_id);
create policy turn_owner_update on tutor.turn for update to authenticated using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy turn_owner_delete on tutor.turn for delete to authenticated using ((select auth.uid()) = user_id);

create policy citation_owner_select on tutor.citation for select to authenticated using ((select auth.uid()) = user_id);
create policy citation_owner_insert on tutor.citation for insert to authenticated with check ((select auth.uid()) = user_id);
create policy citation_owner_update on tutor.citation for update to authenticated using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy citation_owner_delete on tutor.citation for delete to authenticated using ((select auth.uid()) = user_id);

create policy lab_run_owner_select on tutor.lab_run for select to authenticated using ((select auth.uid()) = user_id);
create policy lab_run_owner_insert on tutor.lab_run for insert to authenticated with check ((select auth.uid()) = user_id);
create policy lab_run_owner_update on tutor.lab_run for update to authenticated using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy lab_run_owner_delete on tutor.lab_run for delete to authenticated using ((select auth.uid()) = user_id);

create policy ledger_owner_select on tutor.mastery_ledger for select to authenticated using ((select auth.uid()) = user_id);
create policy ledger_owner_insert on tutor.mastery_ledger for insert to authenticated with check ((select auth.uid()) = user_id);
create policy ledger_owner_update on tutor.mastery_ledger for update to authenticated using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy ledger_owner_delete on tutor.mastery_ledger for delete to authenticated using ((select auth.uid()) = user_id);

comment on function tutor.hybrid_search is
  'RRF fusion of HNSW cosine search and FTS over the official Supabase corpus. Used by the tutor''s search_docs tool and as a teaching example for EXPLAIN.';
