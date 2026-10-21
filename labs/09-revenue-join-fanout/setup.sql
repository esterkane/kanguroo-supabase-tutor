-- Lab 09: the view joins order_items (for items_sold) and order_payments in one go, so every payment is
-- repeated once per item and every item once per payment. Real data, real fan-out.
drop schema if exists lab09 cascade;
create schema lab09;

create view lab09.monthly_revenue as
select date_trunc('month', o.order_purchase_timestamp)::date as month,
       count(distinct o.order_id)                            as orders,
       count(i.order_item_id)                                as items_sold,
       sum(p.payment_value)                                  as revenue
from olist.orders o
join olist.order_items i    on i.order_id = o.order_id
join olist.order_payments p on p.order_id = o.order_id
where o.order_status = 'delivered'
group by 1;
