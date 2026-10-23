-- Lab 03: a correct but slow policy. `auth.uid() = user_id or lab03.is_support_agent()` is evaluated for every
-- row: both functions run ~1M times, and the OR keeps an index on user_id from helping. The orders page times out.
drop schema if exists lab03 cascade;
create schema lab03;
grant usage on schema lab03 to anon, authenticated;

-- SYNTHETIC growth: each real Olist order 10 times (g = 0..9), purchase time shifted by g weeks.
-- user_id: the generated app user of the order's real customer_unique_id (olist.app_users).
create table lab03.orders as
select o.order_id || '-' || g                                  as order_id,
       u.user_id,
       o.order_status,
       o.order_purchase_timestamp + make_interval(weeks => g)  as order_purchase_timestamp
from olist.orders o
join olist.customers c using (customer_id)
join olist.app_users u using (customer_unique_id)
cross join generate_series(0, 9) g;
alter table lab03.orders add primary key (order_id);
analyze lab03.orders;

-- SYNTHETIC: five support agents who may see every order (added with the launch of support-agent access).
create table lab03.support_agents (user_id uuid primary key);
insert into lab03.support_agents select user_id from olist.app_users order by user_id limit 5;

create function lab03.is_support_agent() returns boolean
language sql stable security definer set search_path = '' as $$
  select exists (select 1 from lab03.support_agents where user_id = auth.uid())
$$;
grant execute on function lab03.is_support_agent() to authenticated;

grant select on lab03.orders to authenticated;
alter table lab03.orders enable row level security;
-- The defect: functions called per row (no `select` wrapper), and an OR an index cannot serve.
create policy orders_visible on lab03.orders for select to authenticated
  using (auth.uid() = user_id or lab03.is_support_agent());
