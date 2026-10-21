-- Lab 06: autovacuum disabled on the table (left over from a bulk import) + a job that rewrote every row
-- 10 times. Each UPDATE leaves the old row version behind until VACUUM reclaims it.
drop schema if exists lab06 cascade;
create schema lab06;

create table lab06.orders (like olist.orders including all);
insert into lab06.orders select * from olist.orders;

-- The defect: switched off "temporarily" for the import, never switched back on.
alter table lab06.orders set (autovacuum_enabled = false);

-- The status-sync job, 10 runs. A same-value UPDATE still writes a new row version.
do $$
begin
  for run in 1..10 loop
    update lab06.orders set order_status = order_status;
  end loop;
end $$;
