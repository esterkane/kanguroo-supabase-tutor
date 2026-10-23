begin;
select plan(5);

select has_table('tutor', 'refresh_run', 'refresh runs are recorded');
select is((select relrowsecurity from pg_class where oid = 'tutor.refresh_run'::regclass), true, 'RLS on refresh_run');
select ok(not has_function_privilege('authenticated', 'tutor.trigger_refresh(text)', 'execute'),
          'learners cannot trigger a refresh');
select ok(not has_table_privilege('authenticated', 'tutor.refresh_run', 'select'),
          'learners cannot read refresh runs');
select throws_ok($$ select tutor.trigger_refresh('evil') $$, 'P0001', 'run_trigger must be cron or manual',
                 'only cron/manual triggers are accepted');

select * from finish();
rollback;
