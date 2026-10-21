-- Passes only when the page's query is served by an index in the right order.
begin;
select plan(3);

create function pg_temp.plan_of(q text) returns text language plpgsql as $f$
declare p json;
begin
  execute 'explain (format json) ' || q into p;
  return p::text;
end $f$;

select ok(pg_temp.plan_of($q$
  select order_id, order_status, order_purchase_timestamp, total from lab04.orders
  where customer_unique_id = '8d50f5eadf50201ccdcedfb9e2ac8455'
  order by order_purchase_timestamp desc limit 20 $q$) !~ '"Node Type": "Seq Scan"',
  'no sequential scan over all orders');

select ok(pg_temp.plan_of($q$
  select order_id, order_status, order_purchase_timestamp, total from lab04.orders
  where customer_unique_id = '8d50f5eadf50201ccdcedfb9e2ac8455'
  order by order_purchase_timestamp desc limit 20 $q$) !~ '"Node Type": "(Incremental )?Sort"',
  'rows come out of the index already in page order (no Sort node)');

select results_eq($$
  select count(*)::int from (select 1 from lab04.orders
    where customer_unique_id = '8d50f5eadf50201ccdcedfb9e2ac8455'
    order by order_purchase_timestamp desc limit 20) t $$,
  $$ values (20) $$, 'the page still gets its 20 rows');

select * from finish();
rollback;
