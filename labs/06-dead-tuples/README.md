# Lab 06 — "Our orders table keeps growing although the number of orders doesn't"

**Customer report (redacted):**
> Our orders table has the same number of rows as last month, but it takes several times more space and
> simple counts by status got slower. An hourly status-sync job updates order rows. Do we need a bigger
> instance?

**Environment:** local lab database, table `lab06.orders` with the real Olist orders (99,441 rows). Before
you arrived, the status-sync job rewrote every row 10 times (as real jobs do when they `update ... set
order_status = <same value>`). PostgreSQL 17.

**Evidence to collect (read-only):**

```sql
select count(*) from lab06.orders;
select n_live_tup, n_dead_tup, last_vacuum, last_autovacuum, last_analyze
from pg_stat_user_tables where relid = 'lab06.orders'::regclass;
select pg_size_pretty(pg_table_size('lab06.orders')) as table_size, reloptions
from pg_class where oid = 'lab06.orders'::regclass;
explain (analyze, buffers) select count(*) from lab06.orders where order_status = 'canceled';
```

Compare the size with what 99,441 rows should need: `select pg_size_pretty(pg_table_size('olist.orders'))`
is the same data without the history (on Saru's Mac: 14 MB vs 155 MB).

**Stretch, after the checks pass:** plain VACUUM removed the dead tuples, but did the size or the buffers
of the count query go down? Try `vacuum full lab06.orders` (allowed in this lab) and compare again — then
explain why you would not run it on a busy production table (lock level, rewrite) and what pg_repack does
differently.
Do not read `solution.sql` until the tutor says you have proven the mechanism.
