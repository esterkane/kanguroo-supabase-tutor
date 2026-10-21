-- Lab 05: the export reads with FOR UPDATE, so its session holds row locks on every shipped order for as
-- long as its transaction stays open. The installer then leaves that session idle in transaction.
drop schema if exists lab05 cascade;
create schema lab05;

create table lab05.orders (like olist.orders including all);
insert into lab05.orders select * from olist.orders;
analyze lab05.orders;

-- The courier webhook's update. No lock_timeout of its own: it waits as long as the server lets it.
create function lab05.set_order_status(p_order_id text, p_status text) returns void
language sql as $$
  update lab05.orders set order_status = p_status where order_id = p_order_id
$$;

-- The nightly export. FOR UPDATE was added "to get a consistent snapshot" — it does not do that, it locks rows.
create function lab05.export_batch() returns setof lab05.orders
language sql as $$
  select * from lab05.orders where order_status = 'shipped' order by order_purchase_timestamp for update
$$;
