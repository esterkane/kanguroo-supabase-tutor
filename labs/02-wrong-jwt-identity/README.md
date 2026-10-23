# Lab 02 — "My orders shows only one order, I ordered 17 times"

**Customer report (redacted):**
> A loyal customer (`customer-8d50f5eadf50@example.test`) complains that the "My orders" page shows a single
> order. They have receipts for 17 orders since 2017. Another returning customer sees 1 of 9. New customers are
> fine. Support can see all orders in the dashboard. Is RLS dropping rows, or is the user's token wrong?

**Environment:** local lab database, schema `lab02`. `lab02.orders` holds the real Olist orders (99,441 rows).
`lab02.profiles` is the app's profile table, one row per signed-up user (SYNTHETIC identities: Olist has no
logins; every real `customer_unique_id` got a generated user id). RLS is enabled on both tables.

**Reproduce:** run as role `authenticated` with JWT `sub` = `b83579fb-095b-495e-3c5a-30fd7fcc0b62`
(the lab console has fields for both):

```sql
select order_id, order_status, order_purchase_timestamp, total
from lab02.orders order by order_purchase_timestamp desc;
```

**Evidence you can collect:**

```sql
select auth.uid(), auth.jwt() ->> 'sub';                 -- as authenticated with the sub above
select * from lab02.profiles;                            -- what the app knows about this user
select policyname, cmd, roles, qual from pg_policies where schemaname = 'lab02';
-- as postgres (RLS does not apply to the table owner here):
select customer_unique_id, count(*), count(distinct customer_id)
from lab02.orders where customer_unique_id = '8d50f5eadf50201ccdcedfb9e2ac8455' group by 1;
```

Fix it so every customer sees all of their own orders and still none of anyone else's. Do not read
`solution.sql` until the tutor says you have proven the mechanism.
