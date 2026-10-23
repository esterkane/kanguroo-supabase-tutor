# Lab 03 — "My orders times out since we launched support-agent access"

**Customer report (redacted):**
> Since Tuesday our support agents can see all orders (we extended the RLS policy). Since then the customers'
> "My orders" page fails with `canceling statement due to statement timeout`. We added an index on `user_id`
> as the forum suggested; nothing changed. The table is not that big. What is going on?

**Environment:** local lab database, schema `lab03`. `lab03.orders` has 994,410 rows: the real Olist orders,
each repeated 10 times with shifted dates (SYNTHETIC growth to production size). `user_id` is a generated app
user per real customer (SYNTHETIC identities). Five SYNTHETIC support agents are in `lab03.support_agents`.
The lab's statement timeout is 5 s.

**Reproduce:** run as role `authenticated` with JWT `sub` = `b83579fb-095b-495e-3c5a-30fd7fcc0b62` (a customer
with 17 real orders, so 170 here):

```sql
select order_id, order_status, order_purchase_timestamp
from lab03.orders order by order_purchase_timestamp desc limit 20;
```

**Evidence you can collect:**

```sql
explain select order_id from lab03.orders order by order_purchase_timestamp desc limit 20;   -- as authenticated
select policyname, qual from pg_policies where schemaname = 'lab03';
select pg_get_functiondef('lab03.is_support_agent()'::regprocedure);
-- the same page as postgres (the owner bypasses RLS): how long does it take?
```

Fix it so the page answers well within the timeout for customers and agents still see every order. Do not read
`solution.sql` until the tutor says you have proven the mechanism.
