-- Lab 02: the JWT is right, the identity mapping is not. In Olist, customer_id is per ORDER; the person is
-- customer_unique_id. The policy maps auth.uid() to the customer_id the app stored at sign-up, so a returning
-- customer sees only the order they signed up with.
drop schema if exists lab02 cascade;
create schema lab02;
grant usage on schema lab02 to anon, authenticated;

create table lab02.orders as
select o.order_id, o.customer_id, c.customer_unique_id, o.order_status, o.order_purchase_timestamp,
       coalesce(p.total, 0)::numeric(10,2) as total
from olist.orders o
join olist.customers c using (customer_id)
left join (select order_id, sum(payment_value) as total from olist.order_payments group by order_id) p using (order_id);
alter table lab02.orders add primary key (order_id);
create index on lab02.orders (customer_id);
create index on lab02.orders (customer_unique_id);

-- SYNTHETIC: the app's profile row, written at sign-up from the customer's first order.
create table lab02.profiles (
  user_id            uuid primary key,
  customer_id        text not null,   -- the customer_id of the FIRST order (what the policy uses)
  customer_unique_id text not null,   -- stored too, but unused
  email              text not null
);
insert into lab02.profiles
select distinct on (u.user_id) u.user_id, o.customer_id, u.customer_unique_id, u.email
from olist.app_users u
join lab02.orders o using (customer_unique_id)
order by u.user_id, o.order_purchase_timestamp;
analyze lab02.orders, lab02.profiles;

grant select on lab02.orders, lab02.profiles to authenticated;
alter table lab02.orders enable row level security;
alter table lab02.profiles enable row level security;
create policy profiles_self on lab02.profiles for select to authenticated using ((select auth.uid()) = user_id);

-- The defect: "my orders" = orders with the customer_id from my profile.
create policy orders_own on lab02.orders for select to authenticated
  using (customer_id = (select p.customer_id from lab02.profiles p where p.user_id = (select auth.uid())));
