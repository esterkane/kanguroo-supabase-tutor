-- BEFORE: the dashboard total (inflated by the fan-out)
select sum(revenue) from lab09.monthly_revenue;

-- FIX: one row per order from each child table before joining
create or replace view lab09.monthly_revenue as
with items as (select order_id, count(*) as items from olist.order_items group by order_id),
     pays  as (select order_id, sum(payment_value) as paid from olist.order_payments group by order_id)
select date_trunc('month', o.order_purchase_timestamp)::date as month,
       count(distinct o.order_id)                            as orders,
       coalesce(sum(i.items), 0)::bigint                     as items_sold,
       sum(p.paid)                                           as revenue
from olist.orders o
left join items i using (order_id)
left join pays  p using (order_id)
where o.order_status = 'delivered'
group by 1;

-- AFTER: equals the payments total
select sum(revenue) from lab09.monthly_revenue;

-- MECHANISM: joining two independent one-to-many children multiplies their rows per parent (n x m).
-- Aggregate each child to the parent's grain first; then the join is one-to-one.
