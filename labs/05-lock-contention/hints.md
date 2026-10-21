1. Is the update slow, or is it waiting? A one-row update by primary key that ends in a *lock timeout* is waiting for someone.
2. Who else is connected? Look at `pg_stat_activity`: application name, state and how long its transaction has been open.
3. Row locks are not listed row by row in `pg_locks`. Compare the row's `xmax` with the other session's `backend_xid`.
4. Read `export_batch()`. Which clause takes the locks, and does a read-only export need it? (Under MVCC, plain readers never block writers.)
5. End the stuck session with `pg_terminate_backend(pid)`, remove the locking clause, and give `set_order_status` its own `lock_timeout` so a future blocker makes it fail fast.
