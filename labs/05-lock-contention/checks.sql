-- Passes when the export no longer locks, the webhook fails fast, and no export is left holding locks.
begin;
set local lock_timeout = '2s';
select plan(4);

select ok(pg_get_functiondef('lab05.export_batch()'::regprocedure)
            !~* 'for\s+(update|no\s+key\s+update|share|key\s+share)',
          'export_batch reads without taking row locks');

select results_eq('select count(*)::int from lab05.export_batch()',
                  $$ select count(*)::int from lab05.orders where order_status = 'shipped' $$,
                  'export_batch still exports every shipped order');

select ok(coalesce((select array_to_string(proconfig, ',') from pg_proc
                    where oid = 'lab05.set_order_status(text, text)'::regprocedure), '') ~ 'lock_timeout=',
          'set_order_status has its own lock_timeout');

select is_empty($$
  select pid from pg_stat_activity
  where datname = current_database() and application_name = 'nightly-export'
    and state like 'idle in transaction%'
$$, 'no nightly-export session is left idle in transaction');

select * from finish();
rollback;
