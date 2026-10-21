-- Passes only when every payment and every item is counted exactly once.
begin;
select plan(4);

select has_view('lab09', 'monthly_revenue', 'the dashboard view still exists');
select columns_are('lab09', 'monthly_revenue', array['month', 'orders', 'items_sold', 'revenue'],
                   'the view keeps the columns the dashboard reads');

select is_empty($$
  select v.month
  from lab09.monthly_revenue v
  left join (select date_trunc('month', o.order_purchase_timestamp)::date as month, sum(p.payment_value) as paid
             from olist.orders o join olist.order_payments p using (order_id)
             where o.order_status = 'delivered' group by 1) t using (month)
  where coalesce(v.revenue, 0) is distinct from coalesce(t.paid, 0)
$$, 'revenue per month equals the payments actually made');

select is_empty($$
  select v.month
  from lab09.monthly_revenue v
  left join (select date_trunc('month', o.order_purchase_timestamp)::date as month, count(*) as items
             from olist.orders o join olist.order_items i using (order_id)
             where o.order_status = 'delivered' group by 1) t using (month)
  where coalesce(v.items_sold, 0) is distinct from coalesce(t.items, 0)
$$, 'items_sold per month equals the items actually sold');

select * from finish();
rollback;
