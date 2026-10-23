-- Lab 07: the order-status API connects directly (no pooler), opens a new connection per request and never
-- closes it. Its role has CONNECTION LIMIT 5, so after five requests every new connection is refused (53300).
-- The leaked connections are real sessions the runner opens as lab07_app (lab.yaml scenario_sessions).
drop schema if exists lab07 cascade;
create schema lab07;

do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'lab07_app') then
    create role lab07_app nologin;
  end if;
end $$;
alter role lab07_app nologin connection limit 5;  -- the runner sets LOGIN + a random password at install
alter role lab07_app reset all;                   -- forget an idle_session_timeout from an earlier fix
select pg_terminate_backend(pid) from pg_stat_activity where usename = 'lab07_app';  -- leftovers of a crash

grant usage on schema lab07 to lab07_app;
create table lab07.orders as
select order_id, customer_id, order_status, order_purchase_timestamp from olist.orders;
alter table lab07.orders add primary key (order_id);
analyze lab07.orders;
grant select on lab07.orders to lab07_app;

create function lab07.order_status(p_order_id text) returns table (order_id text, order_status text)
language sql stable as $$
  select o.order_id, o.order_status from lab07.orders o where o.order_id = p_order_id
$$;
grant execute on function lab07.order_status(text) to lab07_app;
