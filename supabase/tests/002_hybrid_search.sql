begin;
select plan(3);

-- Two sources publishing the same page: search must return it once, preferring the docs/guides URL.
-- Test rows carry meta.product 'zz-test' and every query filters on it, so the real corpus
-- (which a zero vector would match arbitrarily) never leaks into the results.
insert into tutor.docs_source (id, url, tier, product) values
  ('aaaaaaaa-0000-0000-0000-000000000001', 'https://example.test/docs/guides/troubleshooting/dup.md', 1, 'kb'),
  ('aaaaaaaa-0000-0000-0000-000000000002', 'https://example.test/kb/troubleshooting/dup.md', 1, 'kb'),
  ('aaaaaaaa-0000-0000-0000-000000000003', 'https://example.test/retired.md', 1, 'kb');
update tutor.docs_source set status = 'retired' where id = 'aaaaaaaa-0000-0000-0000-000000000003';
insert into tutor.docs_chunk (source_id, ord, heading_path, content, content_hash, meta) values
  ('aaaaaaaa-0000-0000-0000-000000000001', 0, 'Dup', 'zebrafish quokka permission denied', 'h-dup', '{"product":"zz-test"}'),
  ('aaaaaaaa-0000-0000-0000-000000000002', 0, 'Dup', 'zebrafish quokka permission denied', 'h-dup', '{"product":"zz-test"}'),
  ('aaaaaaaa-0000-0000-0000-000000000003', 0, 'Old', 'zebrafish quokka retired page', 'h-old', '{"product":"zz-test"}');

select results_eq(
  $$ select count(*)::int from tutor.hybrid_search('zebrafish quokka', array_fill(0, array[768])::extensions.vector(768), 8, array['zz-test']) $$,
  $$ values (1) $$,
  'duplicate chunk text collapses to one hit; retired sources excluded');
select results_eq(
  $$ select url from tutor.hybrid_search('zebrafish quokka', array_fill(0, array[768])::extensions.vector(768), 8, array['zz-test']) $$,
  $$ values ('https://example.test/docs/guides/troubleshooting/dup.md') $$,
  'docs/guides URL wins the tie');
select is_empty(
  $$ select 1 from tutor.hybrid_search('zebrafish', array_fill(0, array[768])::extensions.vector(768), 8, array['zz-other']) $$,
  'source_filter on meta.product excludes non-matching chunks');

select * from finish();
rollback;
