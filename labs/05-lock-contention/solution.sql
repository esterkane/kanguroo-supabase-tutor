-- BEFORE: the webhook's update times out (55P03) while the export session is idle in transaction
select pid, application_name, state, now() - xact_start as xact_age, backend_xid
from pg_stat_activity where datname = current_database() and state like 'idle in transaction%';

-- 1. End the stuck job (lab: only sessions the lab opened can be signalled):
--    select pg_terminate_backend(<pid of nightly-export>);

-- 2. The export reads; MVCC gives it a consistent snapshot without locking anything.
create or replace function lab05.export_batch() returns setof lab05.orders
language sql stable as $$
  select * from lab05.orders where order_status = 'shipped' order by order_purchase_timestamp
$$;

-- 3. Fail fast instead of piling up behind a future blocker.
alter function lab05.set_order_status(text, text) set lock_timeout = '2s';

-- AFTER
select lab05.set_order_status('54282e97f61c23b78330c15b154c867d', 'delivered');

-- MECHANISM: FOR UPDATE takes row locks held until the transaction ends; an idle-in-transaction session
-- keeps them forever. Writers wait on the holder's transaction id (xmax), not on a table lock.
-- PREVENTION in production: short transactions, idle_in_transaction_session_timeout for job roles,
-- lock_timeout for request paths, and alerting on old xact_start in pg_stat_activity.
