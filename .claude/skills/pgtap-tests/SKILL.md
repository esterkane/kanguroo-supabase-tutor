---
name: pgtap-tests
description: Write pgTAP tests for the tutor schema, RLS policies, the hybrid search function, and lab defect checks; run them with `supabase test db`. Use whenever a migration or lab changes.
---

# pgTAP tests

Location: `supabase/tests/*.sql` (CLI picks them up with `npx supabase test db`).
Labs keep their own `checks.sql`, run by `scripts/lab.py check <slug>` against the lab DB
with `pg_prove`-style output parsed by the runner.

## Skeleton
```sql
begin;
select plan(4);
select has_schema('tutor');
select has_function('tutor', 'hybrid_search', array['text','vector','integer','text[]','integer']);
select policies_are('tutor', 'session', array['session_owner_select','session_owner_insert','session_owner_update','session_owner_delete']);
select is((select relrowsecurity from pg_class where oid = 'tutor.session'::regclass), true, 'RLS enabled on tutor.session');
select * from finish();
rollback;
```

## RLS behaviour tests (the important ones)
Use role switching + claims inside the test:
```sql
set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"<uuid-a>","role":"authenticated"}', true);
select results_eq($$ select count(*)::int from tutor.session $$, $$ values (1) $$, 'user A sees only own session');
select throws_ok($$ insert into tutor.session(user_id, objective) values ('<uuid-b>','x') $$, '42501');
reset role;
```
One test per policy per operation; a negative test for every positive one.

## Conventions
- `plan(n)` exact; no `select * from no_plan()`.
- Tests are independent; each file begins with `begin;` and ends with `rollback;`.
- Name tests by mechanism: `'grant missing → 42501 before policy'`.
- Lab `checks.sql` must FAIL on fresh setup and PASS after `solution.sql`; CI runs both directions.
