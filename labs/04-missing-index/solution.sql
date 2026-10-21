-- BEFORE: Seq Scan over ~2M rows + Sort
explain (analyze, buffers)
select order_id, order_status, order_purchase_timestamp, total
from lab04.orders
where customer_unique_id = '8d50f5eadf50201ccdcedfb9e2ac8455'
order by order_purchase_timestamp desc
limit 20;

-- FIX: equality column first, then the ORDER BY column in the same direction
create index lab04_orders_customer_purchase_idx
  on lab04.orders (customer_unique_id, order_purchase_timestamp desc);

-- AFTER: Limit -> Index Scan, no Sort; only the first 20 index entries are needed
explain (analyze, buffers)
select order_id, order_status, order_purchase_timestamp, total
from lab04.orders
where customer_unique_id = '8d50f5eadf50201ccdcedfb9e2ac8455'
order by order_purchase_timestamp desc
limit 20;

-- ROLLBACK (lab only): drop index if exists lab04.lab04_orders_customer_purchase_idx;
-- PRODUCTION: create index concurrently ..., because a plain CREATE INDEX blocks writes on the table.
