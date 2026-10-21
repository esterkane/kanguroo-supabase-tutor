begin;
select plan(4);

select has_column('tutor', 'turn', 'message', 'turn.message stores the verbatim API message');
select has_column('tutor', 'turn', 'seq', 'turn.seq orders messages within a turn');

select set_config('request.jwt.claims', '{"sub":"33333333-3333-3333-3333-333333333333","role":"authenticated"}', true);
set local role authenticated;
insert into tutor.session (id, objective) values ('44444444-4444-4444-4444-444444444444', 'turn test');
insert into tutor.turn (session_id, role, content, message) values
  ('44444444-4444-4444-4444-444444444444', 'user', 'Hallo', '{"role":"user","content":"Hallo"}'),
  ('44444444-4444-4444-4444-444444444444', 'system', '# MODE: lesson', '{"role":"system","content":"# MODE: lesson"}');
select results_eq(
  $$ select role from tutor.turn where session_id = '44444444-4444-4444-4444-444444444444' order by seq $$,
  $$ values ('user'), ('system') $$,
  'system rows are allowed and come back in insertion order');

select set_config('request.jwt.claims', '{"sub":"55555555-5555-5555-5555-555555555555","role":"authenticated"}', true);
select is_empty($$ select 1 from tutor.turn where session_id = '44444444-4444-4444-4444-444444444444' $$,
                'another learner sees none of these turns');
reset role;

select * from finish();
rollback;
