# Lab 04 — "The customer order history page got slow"

**Customer report (redacted):**
> Since our order volume grew, the "My orders" page takes noticeably longer for every customer.
> It shows the 20 most recent orders. We already added more CPU. Please make Postgres faster.

**Environment:** local lab database, table `lab04.orders` (~2 million rows). The rows are the real
Olist orders, each copied 20 times with shifted dates — SYNTHETIC growth, to give the table a
production-like size. Customer `8d50f5eadf50201ccdcedfb9e2ac8455` is the real customer with the most
orders (17 → 340 after the growth). PostgreSQL 17.

**The query the page runs:**

```sql
select order_id, order_status, order_purchase_timestamp, total
from lab04.orders
where customer_unique_id = '8d50f5eadf50201ccdcedfb9e2ac8455'
order by order_purchase_timestamp desc
limit 20;
```

**Evidence to collect (read-only first):**

```sql
explain select ...;                        -- the plan, without running it
explain (analyze, buffers) select ...;     -- runs it: actual rows, time, buffers
select indexname, indexdef from pg_indexes where schemaname = 'lab04';
```

The page must keep returning the same 20 rows. Do not read `solution.sql` until the tutor says you
have proven the mechanism.
