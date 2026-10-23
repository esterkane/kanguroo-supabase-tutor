-- Lab 08 solution: reconcile the schema first, then repair the history, then push.
-- Supabase tracks applied migrations in supabase_migrations.schema_migrations; db push runs the ones missing
-- there, in order: https://supabase.com/docs/guides/deployment/database-migrations.md#how-migration-tracking-works
-- migration repair --status applied marks a migration as applied without running it, and updates the tracking
-- table only: https://supabase.com/docs/guides/deployment/database-migrations.md#step-3-if-the-migration-history-table-is-wrong

-- 1. Make production match 20261005120000 (type and values). In place keeps the column the courier app reads.
alter table lab08.orders alter column delivery_eta type timestamptz using delivery_eta::timestamptz;
update lab08.orders set delivery_eta = order_estimated_delivery_date;

-- 2. Repair: record the migration as applied (what `supabase migration repair --status applied 20261005120000`
--    does to the history table).
insert into lab08.schema_migrations (version, name, statements)
select version, name, statements from lab08.repo_migrations where version = '20261005120000';

-- 3. Push: applies only 20261020100000_late_orders_view.
select * from lab08.db_push();

-- Alternative for step 1: `alter table lab08.orders drop column delivery_eta;` then push both migrations.
-- Simpler, but the courier app loses the column until the push has run. Prevention: no schema changes in the
-- hosted SQL editor; every change goes through a migration (`supabase db diff` can capture one made by hand).
