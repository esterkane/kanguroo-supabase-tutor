-- Lab 04: production-like volume, primary key only. The page's query filters by customer and orders
-- by purchase time, and no index serves both, so every call scans ~2M rows and sorts the matches.
drop schema if exists lab04 cascade;
create schema lab04;

-- SYNTHETIC growth: each real Olist order 20 times (g = 0..19), purchase time shifted by g weeks.
create table lab04.orders as
select o.order_id || '-' || g                                  as order_id,
       c.customer_unique_id,
       o.order_status,
       o.order_purchase_timestamp + make_interval(weeks => g)  as order_purchase_timestamp,
       coalesce(p.total, 0)::numeric(10,2)                     as total
from olist.orders o
join olist.customers c using (customer_id)
left join (select order_id, sum(payment_value) as total from olist.order_payments group by order_id) p
  using (order_id)
cross join generate_series(0, 19) g;

alter table lab04.orders add primary key (order_id);
analyze lab04.orders;
