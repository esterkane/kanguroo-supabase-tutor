1. Same row count, bigger table: what does an UPDATE leave behind under MVCC?
2. `pg_stat_user_tables` counts live and dead row versions and remembers the last (auto)vacuum. What do you see?
3. Autovacuum should have cleaned this up long ago. Why didn't it? Look at the table's `reloptions`.
4. Re-enable autovacuum for the table (`alter table ... reset (...)`), then run `vacuum` on it once yourself.
5. Compare n_dead_tup, the buffers of the count query and the table size before and after. Which one did not shrink, and why?
