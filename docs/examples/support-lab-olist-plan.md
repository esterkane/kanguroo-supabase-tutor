# Example tutoring path: "Supabase Support Lab — from zero to real incidents" (Olist dataset)

Source: a tutoring answer Saru received from an earlier tutor (pasted 2026-10-21). Kept as reference
for the lab track (T2.3 + new O-tasks in TASKS.md) and the first-session flow (T1.10). Lightly cleaned:
inline favicon/image links and "Supabase Docs" source badges were removed; text, commands and tables are
unchanged. Condensed reasoning moves: `prompts/examples/support_lab_plan.md`.

Verified against the ingested corpus on 2026-10-21:
- Node.js 20 or later for the npm/npx CLI install — https://supabase.com/docs/guides/local-development/cli/getting-started.md#install-the-supabase-cli-installing-the-supabase-cli
- OrbStack recommended on macOS — same page, #run-a-local-supabase-project-running-a-local-supabase-project
- `docker network create -o 'com.docker.network.bridge.host_binding_ipv4=127.0.0.1' local-network` +
  `npx supabase start --network-id local-network` — https://supabase.com/docs/guides/local-development.md#quickstart
Unverified (not in the corpus): Olist dataset size/years/file count and its licence (Kaggle page).

Differences from this repo's setup (as of 2026-10-21):
- The tutor already runs a local stack (`make up`) and a disposable `lab` database the tutor can query
  itself (`run_lab_sql`); Olist should be imported there (schema `olist`) so evidence comes from real
  queries, not simulated output — which is exactly what the plan's last line asks for.
- `psql` is not installed on Saru's Mac; the import script uses psycopg `COPY ... FROM STDIN` instead of `\copy`.
- Linking a hosted project and `db push` are learner actions; the tutor never runs CLI commands against a
  hosted project (CLAUDE.md rule 2, T3.2).
- Storage, Realtime and Edge Functions labs need the full local stack, not the `lab` database.

---

# Supabase Support Engineer Lab — From zero to real incidents

Kleinkünstler, this is the right time to stop merely discussing hypothetical customer problems and build a database that we can actually break, inspect, repair and benchmark.

I recommend a local-first approach, followed by a hosted Supabase project. We'll use a real e-commerce dataset, add Supabase authentication and security, and deliberately introduce failures that resemble customer support tickets.

The aim isn't just to make an application. It's to learn what a Support Engineer sees when something goes wrong.

## 1. What we're going to build

Project: Supabase Support Lab (recommended)

Test application / API client (Browser, JavaScript SDK, curl) → Local Supabase (Auth + JWT, PostgREST, Storage, Realtime, Edge Functions, Supavisor, PostgreSQL) → real orders, customers, products, sellers, payments and reviews. Optional hosted development project: cloud metrics, logs, network behavior and deployment practice.

The plan has four stages:

1. Install and validate the Supabase local development environment.
2. Import a real relational dataset and test SQL queries.
3. Add Auth, RLS, APIs, indexes and diagnostic tooling.
4. Reproduce incidents involving slow queries, locks, permissions, migrations, Storage and Realtime.

## 2. Should you run Supabase locally or use its cloud?

Both, but for different reasons.

|                                       | Local Supabase                               | Hosted Supabase              |
| ------------------------------------- | -------------------------------------------- | ---------------------------- |
| Cost                                  | Free locally, uses your computer's resources | Free tier and paid options   |
| PostgreSQL                            | Yes                                          | Yes                          |
| Auth and RLS                          | Yes                                          | Yes                          |
| Storage / Realtime                    | Yes                                          | Yes                          |
| CLI migrations                        | Yes                                          | Yes                          |
| Cloud infrastructure metrics          | No                                           | Yes                          |
| Safe destructive experiments          | Excellent in a disposable lab                | Riskier, even in development |
| Network and deployment investigations | Partial simulation                           | Real hosted behavior         |

My recommendation: Do 80% of your learning locally and use a separate hosted development project for cloud-specific incidents.

Official starting point: [Supabase Local Development](https://supabase.com/docs/guides/local-development). Supabase recommends a Docker-compatible runtime and its CLI for local development.

# Part A — Set up Supabase on macOS

## Step 1. Check what you already have

Open macOS Terminal. Run these commands one at a time:

```
sw_vers
uname -m
node --version
npm --version
docker --version
docker info
brew --version
```

Don't worry if some return `command not found`. We are checking prerequisites, not assuming they're installed.

| Command          | What we want to learn                                  |
| ---------------- | ------------------------------------------------------ |
| `sw_vers`        | macOS version                                          |
| `uname -m`       | Apple Silicon (`arm64`) or Intel (`x86_64`)            |
| `node --version` | Node.js version                                        |
| `npm --version`  | Whether npm is available                               |
| `docker info`    | Whether a Docker-compatible engine is actually running |
| `brew --version` | Whether Homebrew is installed                          |

For npm-based installation, the current Supabase CLI requires Node.js 20 or newer. `docker info` is more useful than `docker --version` alone because the Docker command can exist even when its engine is stopped.

## Step 2. Install a container runtime

For macOS, I'd use OrbStack. OrbStack provides a Docker-compatible engine, allowing Supabase to run its services in containers. Supabase currently recommends it on macOS. [OrbStack official website](https://orbstack.dev/)

Alternatively, Docker Desktop works.

After installing and launching the runtime:

```
docker info
```

Expected: Docker server information rather than a message saying the daemon is unreachable.

There is also an experimental native runtime for Apple Silicon Macs running macOS 14 or later. For our first lab, I'd prefer the standard container-based setup because it matches the widely documented CLI workflow.

## Step 3. Create the lab directory

Assuming Node.js and npm are available:

```
mkdir -p ~/supabase-support-lab
cd ~/supabase-support-lab

npm init -y
npm install supabase --save-dev
```

Verify the installed CLI:

```
npx supabase --version
```

The version printed by that command will be our actual lab version. We should record it rather than assume a particular release.

## Step 4. Initialize Supabase

```
npx supabase init
```

Expected project structure:

```
supabase-support-lab/
├── package.json
├── package-lock.json
├── node_modules/
└── supabase/
    └── config.toml
```

This step creates local project configuration. It doesn't automatically create a hosted cloud project.

## Step 5. Start the local stack

```
npx supabase start
```

On first startup, the CLI downloads the required service images and starts the environment.

For a Mac on an untrusted network, use Supabase's documented localhost-binding network configuration before starting the stack:

```
docker network create \
  -o 'com.docker.network.bridge.host_binding_ipv4=127.0.0.1' \
  local-network

npx supabase start --network-id local-network
```

Use that version of the start command instead of the ordinary one if you've created the dedicated network. Do not expose your lab publicly.

## Step 6. Inspect your running services

```
npx supabase status
```

A typical default local installation exposes:

| Service             | Typical local address    |
| ------------------- | ------------------------ |
| Studio Dashboard    | `http://127.0.0.1:54323` |
| Supabase API        | `http://127.0.0.1:54321` |
| PostgreSQL          | `127.0.0.1:54322`        |
| Local email testing | Address printed by CLI   |

The exact addresses and credentials are given by `supabase status`. Use those values rather than hardcoding assumptions.

Open the Studio URL in your browser. You should now have a usable local Supabase Dashboard and PostgreSQL database.

## Step 7. Verify PostgreSQL works

Open SQL Editor in local Studio and execute:

```
select
  current_database() as database_name,
  current_user as database_role,
  version() as postgres_version;
```

Expected: one row containing the local database name, active database role and PostgreSQL version.

We're not predicting the exact version; the query will tell us what's actually running.

Then try:

```
select count(*)
from pg_stat_activity;
```

Expected: a nonnegative count of database sessions. This confirms that one of our core future diagnostic views is available.

Rollback / cleanup: For now, simply stop the stack when you aren't using it:

```
npx supabase stop
```

Do not use `--no-backup` casually; that option discards local data and schema changes that haven't been preserved.

# Part B — Choose a real dataset

I looked for datasets that are complex enough to create realistic PostgreSQL incidents rather than just simple SQL exercises.

My first choice is the Olist Brazilian E-Commerce dataset.

## [Brazilian E-Commerce Public Dataset by Olist](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce)

Best starting dataset. ~100,000 orders, 2016–2018. Real, anonymized e-commerce data covering orders, payments, products, customers, sellers, reviews and locations. Ideal for relational SQL, query performance, indexing, transaction scenarios and support troubleshooting.

[NYC Taxi Trip Records](https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page): very large trip datasets, excellent for table growth, indexes, partitioning, aggregation, storage pressure and slow-query investigations. Less suitable for introductory multi-table relational modeling.

[Stack Exchange Data Dumps](https://archive.org/details/stackexchange): questions, answers, comments and users with relational connections. Good for full-text search, joins, analytics and larger datasets. More effort to import and adapt to application-level Auth.

## Why Olist is a particularly good choice

It contains nine related CSV datasets, including orders, order items, payments, customers, products and sellers.

Simplified Olist relational model: customers (customer IDs, locations) → orders (order ID, customer ID, timestamps, status) → order_items (products, sellers, prices); orders → payments (amounts, methods); orders → reviews (scores, comments); order_items → products, sellers. Conceptual relationships only; the complete data model also includes category translations and geolocation records.

A particularly good feature: this is historical commercial data, not a purpose-built Supabase demo. We can import it as raw business data, and then add authentication, tenants, roles and RLS ourselves.

That gives us practice investigating realistic differences between an application's data model and its security model.

# Part C — Import the dataset into PostgreSQL

I suggest a two-stage import: raw CSV tables first, then properly modeled relational tables.

This gives us two useful environments: messy imported data and a cleaned, normalized application schema.

## Step 1. Download Olist

Open the [Olist dataset on Kaggle](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) and download its ZIP archive.

Extract the archive into:

```
supabase-support-lab/
└── data/
    └── olist/
        ├── olist_orders_dataset.csv
        ├── olist_order_items_dataset.csv
        ├── olist_customers_dataset.csv
        ├── olist_order_payments_dataset.csv
        ├── ...
```

Keep the original CSVs unchanged.

## Step 2. Create a staging schema

In your local Supabase SQL Editor, run:

```
create schema if not exists staging;
```

We'll use `staging` for the raw imported data and `public` for the eventual application tables.

This keeps our training work separate from Auth and Supabase-managed schemas.

## Step 3. Create our first staging table

Let's start with orders, one of the most important tables.

```
create table staging.orders_raw (
  order_id text,
  customer_id text,
  order_status text,
  order_purchase_timestamp text,
  order_approved_at text,
  order_delivered_carrier_date text,
  order_delivered_customer_date text,
  order_estimated_delivery_date text
);
```

Notice that we're initially storing timestamps as text.

That's deliberate for our staging layer. It lets us load the raw CSV without immediately rejecting invalid or missing timestamps. We'll convert to appropriate SQL types in a later transformation.

## Step 4. Import the CSV

For a first small import, the Supabase Table Editor supports CSV uploads, but local PostgreSQL's `\copy` command is more flexible for larger imports.

Using a PostgreSQL `psql` client connected to your local database, import the file:

```
\copy staging.orders_raw
FROM '/absolute/path/to/olist_orders_dataset.csv'
WITH (FORMAT csv, HEADER true);
```

Replace the path with your actual CSV location.

`\copy` is a `psql` client command, not ordinary SQL. Run it in a terminal `psql` session, not the Dashboard SQL Editor.

For example, if `psql` is installed and your local stack uses the default database port, you can establish a connection using the connection details from `npx supabase status`. Avoid putting passwords directly in shell history; use an interactive password prompt or a securely managed local environment.

The CSV import methods are described in [Supabase's official import guide](https://supabase.com/docs/guides/database/import-data).

## Step 5. Verify the import

```
select count(*)
from staging.orders_raw;
```

For the commonly distributed Olist dataset, expect approximately 100,000 orders, though the exact number should be verified from your downloaded files.

Then inspect the statuses:

```
select
  order_status,
  count(*) as order_count
from staging.orders_raw
group by order_status
order by order_count desc;
```

And check for missing values:

```
select
  count(*) filter (
    where order_delivered_customer_date is null
       or order_delivered_customer_date = ''
  ) as missing_delivery_dates
from staging.orders_raw;
```

These queries begin our real data-quality work.

The staging table is disposable. Once we're happy with the data, we'll design properly typed tables, primary keys, foreign keys and indexes through versioned migrations.

Cleanup: If you want to discard just this imported practice table, after confirming it's the disposable copy:

```
drop table staging.orders_raw;
```

We won't delete anything in a production or customer database.

# Part D — Use the dataset for real Supabase incidents

Once the raw data is loaded, we'll add a clean schema and deliberately broken scenarios.

Here's the curriculum I recommend.

| Lab                   | Deliberate failure                | What you'll learn                        |
| --------------------- | --------------------------------- | ---------------------------------------- |
| 1. SQL foundations    | Incorrect joins duplicate revenue | Joins, cardinality, aggregation          |
| 2. Performance        | Missing composite index           | EXPLAIN, indexes, buffer reads           |
| 3. Query workload     | Excessive repeated queries        | `pg_stat_statements`, query frequency    |
| 4. Locking            | Transaction left open             | MVCC, locks, blockers, timeouts          |
| 5. RLS                | Customer cannot see an order      | JWT, GRANT, policies                     |
| 6. Migrations         | Works locally, fails remotely     | Schema drift, migration history          |
| 7. Connection pooling | Too many concurrent connections   | Supavisor, session and transaction pools |
| 8. Storage            | Product image upload fails        | Buckets, permissions, signed URLs        |
| 9. Realtime           | Order status updates don't arrive | Subscriptions, WAL, replication          |
| 10. Edge Functions    | Webhook returns a 500             | Runtime logs, deployment, secrets        |
| 11. Operations        | Database fills with dead tuples   | VACUUM, bloat, WAL                       |
| 12. Recovery          | Accidental data modification      | Backups, restore, PITR concepts          |

Some exercises require synthetic application data that we'll add alongside Olist. For example, the dataset doesn't automatically have Supabase Auth accounts, and its historical rows are not already associated with JWT identities.

We'll create fictional test users and mapping tables rather than pretending those relationships already exist.

## Make the lab reproducible with migrations and seeds

Eventually our project will look like:

```
supabase-support-lab/
├── data/
│   └── olist/
├── supabase/
│   ├── config.toml
│   ├── migrations/
│   │   ├── <timestamp>_create_schema.sql
│   │   ├── <timestamp>_add_indexes.sql
│   │   └── <timestamp>_add_policies.sql
│   └── seed.sql
├── tests/
└── README.md
```

We can create migrations with:

```
npx supabase migration new create_ecommerce_schema
```

After filling in the migration and seed files, we can test reproducibility locally:

```
npx supabase db reset
```

Warning: `db reset` reconstructs the local database from migrations and configured seeds, discarding unpreserved local changes. Use it only after you've saved the schema and any data you need.

Supabase's [seeding documentation](https://supabase.com/docs/guides/local-development/seeding-your-database) explains the migration-then-seed sequence.

Large raw CSVs need not go into `seed.sql`; we'll later build a repeatable bulk-import script so we can regenerate the training data without keeping massive SQL inserts in Git.

# Part E — Add a hosted Supabase project

Once the local database works, we should also create a hosted development environment.

This gives you experience with actual Supabase infrastructure.

Step 1. Open [Supabase Dashboard](https://supabase.com/dashboard) and create a new project dedicated to training.

Step 2. Choose a region, record your PostgreSQL version, and keep your generated database password securely.

Step 3. Install and authenticate the CLI if you haven't already:

```
npx supabase login
```

Step 4. Link your local repository to your hosted development project:

```
npx supabase link --project-ref YOUR_PROJECT_REF
```

Step 5. Preview unapplied migrations:

```
npx supabase db push --dry-run
```

Only after reviewing the changes should you consider applying them with `npx supabase db push`.

Step 6. Use the hosted Dashboard's Logs and Observability areas to investigate performance and operational behavior.

We won't upload the entire Olist dataset immediately or generate artificial high traffic against a shared hosted project. Start with a small, controlled subset, check the project's resource limits, and keep stress tests local.

Official documentation: [Local-to-hosted development workflows](https://supabase.com/docs/guides/local-development/cli-workflows).

## Your first checkpoint: verify your Mac

Let's do this incrementally rather than running through twenty installation steps with unverified prerequisites.

Open Terminal and run:

```
sw_vers
uname -m
node --version
npm --version
docker --version
docker info
```

Paste the output here. You can omit your machine's hostname and other personal details.

From that, we'll determine what is already installed, get the local Supabase stack running, and load our first Olist table.

Our first practical support case will then be a deliberately slow order query. You'll collect a real execution plan, identify its bottleneck, test a fix and measure the improvement.

No simulated outputs once the lab is operational. We'll work with evidence from your actual environment.
