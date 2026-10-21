-- BEFORE
select n_live_tup, n_dead_tup, last_autovacuum from pg_stat_user_tables where relid = 'lab06.orders'::regclass;
select pg_size_pretty(pg_table_size('lab06.orders')), reloptions from pg_class where oid = 'lab06.orders'::regclass;

-- FIX: let autovacuum do its job again, and clean up the backlog now
alter table lab06.orders reset (autovacuum_enabled);
vacuum lab06.orders;

-- AFTER: dead tuples gone, every page all-visible; the file is mostly the same size — plain VACUUM makes
-- the space reusable for new rows but returns it to the OS only at the end of the table. Shrinking the
-- file needs VACUUM FULL (ACCESS EXCLUSIVE lock, rewrites the table) or pg_repack — a separate decision.
select n_live_tup, n_dead_tup, last_vacuum from pg_stat_user_tables where relid = 'lab06.orders'::regclass;
