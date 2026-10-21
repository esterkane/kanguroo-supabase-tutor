# Lab 05 — "Marking orders as delivered times out since the export job was added"

**Customer report (redacted):**
> Our courier webhook calls `lab05.set_order_status(order_id, 'delivered')`. Since we added a nightly
> export job, many of these calls fail with `canceling statement due to lock timeout` — always for
> orders that are still `shipped`. The export itself "finished hours ago". Is Postgres overloaded?

**Environment:** local lab database, schema `lab05` with the real Olist orders (`lab05.orders`, 99,441
rows; 1,107 of them `shipped`). When the lab is installed, a real second database session starts with
`application_name = 'nightly-export'` and runs `lab05.export_batch()`. It is still connected.

**Reproduce (one of the real shipped orders):**

```sql
select lab05.set_order_status('54282e97f61c23b78330c15b154c867d', 'delivered');
```

**Evidence you can collect:**

```sql
select pid, application_name, state, now() - xact_start as xact_age, backend_xid, left(query, 60) as query
from pg_stat_activity where datname = current_database() and pid <> pg_backend_pid();

select locktype, relation::regclass, mode, granted, pid from pg_locks where pid <> pg_backend_pid();

select xmax from lab05.orders where order_id = '54282e97f61c23b78330c15b154c867d';
select pg_get_functiondef('lab05.export_batch()'::regprocedure);
```

Fix it so (1) the stuck job no longer blocks, (2) the export cannot block status updates again, and (3) the
webhook's update fails fast instead of waiting when something else does hold a lock. Do not read
`solution.sql` until the tutor says you have proven the mechanism.
