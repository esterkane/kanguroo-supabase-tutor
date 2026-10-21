-- Passes only after the defect is fixed.
begin;
select plan(3);

select set_config('request.jwt.claims', '{"sub":"11111111-1111-1111-1111-111111111111","role":"authenticated"}', true);
set local role authenticated;

select lives_ok($$ select * from lab01.orders $$, 'authenticated can SELECT (grant present)');
select results_eq($$ select count(*)::int from lab01.orders $$, $$ values (10) $$, 'RLS still limits to own rows');

reset role;
select is((select relrowsecurity from pg_class where oid = 'lab01.orders'::regclass), true, 'RLS was not disabled as a "fix"');

select * from finish();
rollback;
