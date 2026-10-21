# Lab 09 — "The dashboard says revenue is 28 % higher than our payment provider"

**Customer report (redacted):**
> Our finance dashboard reads from the view `monthly_revenue`. For delivered orders it shows a total of
> 19,776,160.44, but the payment provider settled 15,422,461.77 for the same orders. Nobody changed the
> payments. Is Postgres summing wrong?

**Environment:** local lab database, schema `lab09`, view `lab09.monthly_revenue` over the real Olist
e-commerce data in schema `olist` (orders, order_items, order_payments). PostgreSQL 17.
The numbers above are what this view returns on the real dataset — you can reproduce them.

**Available evidence:**

```sql
select sum(revenue) from lab09.monthly_revenue;           -- what the dashboard shows

select sum(p.payment_value)                                -- what was actually paid
from olist.orders o
join olist.order_payments p using (order_id)
where o.order_status = 'delivered';

select pg_get_viewdef('lab09.monthly_revenue'::regclass, true);
```

The view must keep its columns (`month`, `orders`, `items_sold`, `revenue`) because the dashboard reads
them. Do not read `solution.sql` until the tutor says you have proven the mechanism.
