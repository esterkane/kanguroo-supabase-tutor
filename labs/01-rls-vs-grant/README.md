# Lab 01 — "RLS is broken, users can't see their orders"

**Customer report (redacted):**
> We added an RLS policy so each customer only sees their own orders. Since this
> morning every logged-in user gets `permission denied for table orders`. The policy
> looks right. Please fix RLS.

**Environment:** local lab database, schema `lab01`, table `lab01.orders`,
roles `authenticated` / `anon` as in a Supabase project. Postgres 17.

**Available evidence (run as the customer's app would):**

```sql
begin;
set local role authenticated;
select set_config('request.jwt.claims',
  '{"sub":"11111111-1111-1111-1111-111111111111","role":"authenticated"}', true);
select * from lab01.orders;
rollback;
```

Collect the SQLSTATE and message. Then look at `pg_policies` and `\dp lab01.orders`.

Do not read `solution.sql` until the tutor says you have proven the mechanism.
