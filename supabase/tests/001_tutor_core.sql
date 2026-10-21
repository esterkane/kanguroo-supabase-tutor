begin;
select plan(16);

select has_schema('tutor');
select has_table('tutor', 'docs_chunk', 'docs_chunk exists');
select has_table('tutor', 'session', 'session exists');
select has_function('tutor', 'hybrid_search', 'hybrid_search exists');

select is((select relrowsecurity from pg_class where oid = 'tutor.session'::regclass), true, 'RLS on session');
select is((select relrowsecurity from pg_class where oid = 'tutor.turn'::regclass), true, 'RLS on turn');
select is((select relrowsecurity from pg_class where oid = 'tutor.mastery_ledger'::regclass), true, 'RLS on mastery_ledger');
select is((select relrowsecurity from pg_class where oid = 'tutor.docs_chunk'::regclass), true, 'RLS on docs_chunk');
select is_empty(
  $$ select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace
     where n.nspname = 'tutor' and c.relkind = 'r' and not c.relrowsecurity $$,
  'every table in schema tutor has RLS enabled');
select policies_are('tutor', 'session',
  array['session_owner_select','session_owner_insert','session_owner_update','session_owner_delete'],
  'session has exactly the four owner policies');
select cmp_ok((select count(*)::int from tutor.topic), '>', 0, 'topics seeded from curriculum.yaml');
select ok(exists(select 1 from tutor.lab where slug = '01-rls-vs-grant'), 'lab 01 registered');

-- user A can only see own sessions; cannot insert as another user
select set_config('request.jwt.claims', '{"sub":"11111111-1111-1111-1111-111111111111","role":"authenticated"}', true);
set local role authenticated;
insert into tutor.session (objective) values ('test A');
select results_eq($$ select count(*)::int from tutor.session $$, $$ values (1) $$, 'A sees exactly own session');
select throws_ok(
  $$ insert into tutor.session (user_id, objective) values ('22222222-2222-2222-2222-222222222222', 'as B') $$,
  '42501', null, 'A cannot insert a session owned by B');

select set_config('request.jwt.claims', '{"sub":"22222222-2222-2222-2222-222222222222","role":"authenticated"}', true);
select results_eq($$ select count(*)::int from tutor.session $$, $$ values (0) $$, 'B sees none of A''s sessions');
reset role;

-- hybrid_search is callable with an empty corpus
select lives_ok(
  $$ select * from tutor.hybrid_search('rls grant', array_fill(0, array[768])::extensions.vector(768), 3) $$,
  'hybrid_search runs on empty corpus');

select * from finish();
rollback;
