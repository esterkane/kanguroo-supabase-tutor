# Lab 08 — "`supabase db push` fails: column delivery_eta already exists"

**Customer report (redacted):**
> We want to deploy a new migration (`20261020100000_late_orders_view`). `supabase db push` stops at an older
> one: `ERROR: column "delivery_eta" of relation "orders" already exists (SQLSTATE 42701)` while applying
> `20261005120000_add_delivery_eta`. Locally everything works. Someone suggested `supabase migration repair`.
> Can we just do that?

**Environment:** local lab database, schema `lab08`, standing in for the hosted project. `lab08.orders` holds
the real Olist orders (99,441 rows). The repo's `supabase/migrations` folder is modelled as the table
`lab08.repo_migrations`, the remote history table `supabase_migrations.schema_migrations` as
`lab08.schema_migrations`. `lab08.migration_list()` and `lab08.db_push()` behave like the CLI commands for
this lab: list local vs remote versions, and apply what the remote history lacks, in order.

**Reproduce:**

```sql
select * from lab08.db_push();
```

**Evidence you can collect:**

```sql
select * from lab08.migration_list();
select * from lab08.repo_migrations where version = '20261005120000';
select column_name, data_type from information_schema.columns
where table_schema = 'lab08' and table_name = 'orders' order by ordinal_position;
select order_id, order_purchase_timestamp, order_estimated_delivery_date, delivery_eta from lab08.orders limit 5;
```

Fix it so `db_push()` deploys the new migration and production really is in the state the migrations
describe. Persist your steps (they are declared persistent in this lab). Do not read `solution.sql` until the
tutor says you have proven the mechanism.
