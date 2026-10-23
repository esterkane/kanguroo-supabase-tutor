-- Lab 08: migration drift. "Production" (schema lab08) got a manual hotfix column that the migration history
-- does not know, with a different type and different values than the repo's migration. `db push` therefore
-- re-runs that migration and fails with 42701; marking it applied alone would keep the wrong column.
-- lab08.repo_migrations models the repo's supabase/migrations folder; lab08.schema_migrations models the
-- remote history table supabase_migrations.schema_migrations; db_push() and migration_list() model the CLI.
drop schema if exists lab08 cascade;
create schema lab08;

create table lab08.orders as
select order_id, customer_id, order_status, order_purchase_timestamp, order_estimated_delivery_date
from olist.orders;
alter table lab08.orders add primary key (order_id);

-- The repo: four migrations, in version order.
create table lab08.repo_migrations (version text primary key, name text not null, statements text[] not null);
insert into lab08.repo_migrations values
  ('20261001090000', 'orders_baseline', array['select 1 -- baseline: lab08.orders existed before migrations']),
  ('20261005120000', 'add_delivery_eta', array[
     'alter table lab08.orders add column delivery_eta timestamptz',
     'update lab08.orders set delivery_eta = order_estimated_delivery_date']),
  ('20261010080000', 'index_order_status', array['create index orders_status_idx on lab08.orders (order_status)']),
  ('20261020100000', 'late_orders_view', array[
     'create view lab08.late_orders as select order_id, order_status, delivery_eta from lab08.orders '
     'where order_status not in (''delivered'', ''canceled'') and delivery_eta < now()']);

-- The remote history: 20261005120000 is missing; 20261020100000 is the new migration the team wants to push.
create table lab08.schema_migrations (version text primary key, name text, statements text[]);
insert into lab08.schema_migrations select * from lab08.repo_migrations
where version in ('20261001090000', '20261010080000');
create index orders_status_idx on lab08.orders (order_status);

-- SYNTHETIC drift: on 2026-10-04 someone added the column by hand in the SQL editor as a courier-app hotfix,
-- as a date, filled with a guess (purchase + 21 days) instead of Olist's estimated delivery date.
alter table lab08.orders add column delivery_eta date;
update lab08.orders set delivery_eta = order_purchase_timestamp::date + 21;
analyze lab08.orders;

create function lab08.migration_list() returns table (local text, remote text, name text)
language sql stable as $$
  select r.version, h.version, coalesce(r.name, h.name)
  from lab08.repo_migrations r full join lab08.schema_migrations h on h.version = r.version
  order by coalesce(r.version, h.version)
$$;

create function lab08.db_push() returns table (version text, name text, result text)
language plpgsql as $$
#variable_conflict use_column
declare m record; stmt text;
begin
  for m in select r.version, r.name, r.statements from lab08.repo_migrations r
           where not exists (select 1 from lab08.schema_migrations h where h.version = r.version)
           order by r.version loop
    foreach stmt in array m.statements loop
      execute stmt;
    end loop;
    insert into lab08.schema_migrations (version, name, statements) values (m.version, m.name, m.statements);
    version := m.version; name := m.name; result := 'applied';
    return next;
  end loop;
end $$;
