# Lab 07 — "FATAL: too many connections for role" after a few requests

**Customer report (redacted):**
> Our order-status API (Node, one `new pg.Client()` per request, connecting directly to Postgres, not through
> the pooler) works after a deploy, then fails with `FATAL: too many connections for role "lab07_app"`.
> Restarting the API "fixes" it until the next few requests. Do we need a bigger instance?

**Environment:** local lab database, schema `lab07` with the real Olist orders (99,441 rows). The API logs in
as its own role `lab07_app`. When the lab is installed, the API's last five requests are real database
sessions logged in as `lab07_app` (application `orders-api`); they are still connected.

**Reproduce:** the API's next request opens one new connection as `lab07_app` and asks for a real order. Use
the lab's **reproduce** button (or ask the tutor to reproduce it).

**Evidence you can collect** (as postgres):

```sql
select current_setting('max_connections')::int as max_connections, count(*) as connections_now
from pg_stat_activity;
select rolname, rolconnlimit, rolconfig from pg_roles where rolname = 'lab07_app';
select pid, usename, application_name, state, now() - state_change as idle_for, left(query, 60) as last_query
from pg_stat_activity where usename = 'lab07_app';
```

Fix it so (1) the API can connect again now, (2) the database closes connections the API forgets, and
(3) explain what the API should do instead. Here you may end a leaked session with
`select pg_terminate_backend(<pid>)`, one pid per statement. Do not read `solution.sql` until the tutor says
you have proven the mechanism.
