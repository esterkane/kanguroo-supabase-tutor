begin;
select plan(2);

-- 300 decoys sit exactly on the query vector; the 3 filtered rows are close behind them
-- (cosine distance ~0.03). A plain HNSW scan yields ef_search candidates, all decoys, and the
-- filter leaves nothing; an iterative scan keeps going and reaches the targets.
insert into tutor.docs_source (id, url, tier, product) values
  ('bbbbbbbb-0000-0000-0000-000000000001', 'https://example.test/decoys.md', 1, 'zz-noise'),
  ('bbbbbbbb-0000-0000-0000-000000000002', 'https://example.test/target.md', 1, 'zz-target');
insert into tutor.docs_chunk (source_id, ord, content, content_hash, meta, embedding)
select 'bbbbbbbb-0000-0000-0000-000000000001', g, 'decoy ' || g, 'decoy-' || g, '{"product":"zz-noise"}',
       array_fill(1, array[768])::extensions.vector(768)
from generate_series(1, 300) g;
insert into tutor.docs_chunk (source_id, ord, content, content_hash, meta, embedding)
select 'bbbbbbbb-0000-0000-0000-000000000002', g, 'target ' || g, 'target-' || g, '{"product":"zz-target"}',
       (array_fill(0.5, array[100]) || array_fill(1, array[668]))::extensions.vector(768)
from generate_series(1, 3) g;

select results_eq(
  $$ select count(*)::int from tutor.hybrid_search('qqqzzz', array_fill(1, array[768])::extensions.vector(768), 8,
                                                   array['zz-target']) $$,
  $$ values (3) $$,
  'filtered semantic search still finds rows outside the unfiltered nearest neighbours');
select ok(
  (select proconfig @> array['hnsw.iterative_scan=relaxed_order'] from pg_proc
   where oid = 'tutor.hybrid_search(text, extensions.vector, integer, text[], integer)'::regprocedure),
  'hybrid_search pins hnsw.iterative_scan');

select * from finish();
rollback;
