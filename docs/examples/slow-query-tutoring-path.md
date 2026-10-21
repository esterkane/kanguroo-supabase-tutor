# Example tutoring path: high CPU → slow query → composite index → buffers

Source: a tutoring session Saru ran with an earlier version of the Känguru tutor (pasted 2026-10-21).
Kept verbatim as reference material for prompts, evals (T1.11) and lab 04 (T2.3). All numbers and
plans in it are fictional training data. Citations in the original were rendered as "Supabase Docs" /
"PostgreSQL" labels without URLs; the original also cites PostgreSQL 18 docs while the local stack
runs PostgreSQL 17. Condensed reasoning moves: `prompts/examples/slow_query_path.md`.

---

**Learner:** I would like to know first which query is slow and what it looks like. Than I would like to corralate the ressources used to this query and check for bottlenecks

**Tutor:** Good approach, Kleinkünstler. You're proposing to identify the expensive SQL first, understand what it does, and then correlate its behavior with CPU, memory, I/O and other bottlenecks.

For our incident, that's a sensible priority because:

- Database CPU is at 91%.
- 65 sessions are active without a reported wait event.
- Only 2 sessions are waiting on locks.
- Connections are at 85 out of 200.
- API traffic doubled yesterday.

CPU-intensive query execution is therefore a stronger initial hypothesis than connection exhaustion or widespread lock contention.

But here's an important distinction: high cumulative query time doesn't necessarily mean an individual query is slow. A 5 ms query executed 100,000 times can be a bigger problem than one 2-second query executed ten times.

We need to examine both frequency and execution time.

1. Find the queries consuming the most database time

Supabase uses PostgreSQL's pg_stat_statements extension to collect aggregated query statistics.

Assuming it's enabled, we can ask the customer to run this read-only query:

```sql
select
  calls,
  round(mean_exec_time::numeric, 1) as avg_ms,
  round(total_exec_time::numeric, 1) as total_ms,
  left(query, 120) as query
from pg_stat_statements
order by total_exec_time desc
limit 10;
```

This gives us the most expensive queries by cumulative execution time across the statistics collection period. We would also check when those statistics were reset.

Official documentation: Supabase — Query Performance Monitoring. (Supabase Docs)

2. The customer returns these results

Fictional training data — not measurements from a real database.

| Query | Calls | Avg. time | Total time |
|---|---|---|---|
| A — Fetch recent orders | 200,000 | 45 ms | 9,000,000 ms |
| B — Generate sales report | 500 | 2,000 ms | 1,000,000 ms |
| C — Fetch customer profile | 100,000 | 3 ms | 300,000 ms |

Cumulative query execution time (illustrative totals in database-hours; accumulated CPU/wall execution across calls, not individual request latency): A: Orders 2.5 h · B: Reports 0.3 h · C: Profiles 0.1 h.

Query A stands out because it consumes the most cumulative execution time, despite not being the slowest individual query.

This makes it a good candidate for investigation. It still doesn't prove that Query A is responsible for the 91% CPU, because execution time isn't the same measurement as CPU time.

3. Inspect the actual SQL

The customer provides Query A:

```sql
select id, customer_id, total, created_at
from public.orders
where customer_id = 12345
order by created_at desc
limit 20;
```

And this fictional execution plan:

```
Limit
  (actual time=42.1..44.8 rows=20 loops=1)
  -> Sort
       Sort Key: created_at DESC
       Sort Method: top-N heapsort
       -> Seq Scan on orders
            (actual rows=350 loops=1)
            Filter: (customer_id = 12345)
            Rows Removed by Filter: 1999650

Execution Time: 45.1 ms
```

Let's interpret just the important parts. What PostgreSQL did:

- Sequential Scan — PostgreSQL examined the table's rows and rejected almost two million that didn't match the customer ID.
- Sort — It ordered the 350 matching rows by creation date.
- Limit — It returned the 20 newest matching orders.

This plan suggests that repeatedly scanning two million orders might be costly.

But we still shouldn't blindly create an index. We'd inspect existing indexes, selectivity, planner estimates, buffer activity and workload patterns, then compare a candidate improvement in a safe test environment. Supabase and PostgreSQL both recommend examining execution plans before optimizing. (Supabase Docs +1)

How do we obtain the plan? For a production database, we could initially request a non-executing plan:

```sql
explain
select id, customer_id, total, created_at
from public.orders
where customer_id = 12345
order by created_at desc
limit 20;
```

EXPLAIN shows the optimizer's planned execution. EXPLAIN ANALYZE actually executes the query and adds runtime measurements; that should be used deliberately, especially for expensive queries or writes. (PostgreSQL)

Your next exercise: interpreting an execution plan. We know Query A has these characteristics:

- Two million orders.
- Filters by customer_id.
- Sorts by created_at DESC.
- Returns the latest 20 orders.
- Executes 200,000 times during the observed statistics period.

One question: If you were investigating whether an index could improve this query, which columns would you examine first, and why?

You don't need to know PostgreSQL index syntax yet. Think about what the query is trying to find and in what order.

---

**Learner:** if we are constantly returning latest 20 orders, do we need the complete data set everytime by the customer id, or can we implement a time frame that would make sense for the query and not search through all of the rows

**Tutor:** Kleinkünstler, that's a good performance-engineering hypothesis. You're questioning whether the database needs to consider two million orders every time someone asks for the latest 20.

Your suggestion is called reducing the search space. It can improve performance, but there's a subtle distinction:

Restricting the data by time is not necessarily the best solution. A suitable index might let PostgreSQL find the latest 20 orders without scanning the entire table or adding a time restriction.

Let's compare.

1. Your proposed solution: add a time filter

Original query:

```sql
select id, customer_id, total, created_at
from public.orders
where customer_id = 12345
order by created_at desc
limit 20;
```

Your idea might look like:

```sql
select id, customer_id, total, created_at
from public.orders
where customer_id = 12345
  and created_at >= now() - interval '30 days'
order by created_at desc
limit 20;
```

This retrieves at most 20 orders from the past 30 days.

But what happens if the customer placed their last order 45 days ago?

The query returns nothing, even though the customer has orders.

We've changed the meaning of the query. That might be acceptable for a "Recent 30 days" page, but not for a "Latest 20 orders" page.

And without a suitable index, PostgreSQL might still need to scan a large portion of the table to evaluate the time condition.

2. An alternative: an index supporting filtering and sorting

Consider a composite B-tree index:

```sql
create index orders_customer_created_idx
on public.orders (
  customer_id,
  created_at desc
);
```

- The first column helps PostgreSQL find orders belonging to the requested customer.
- The second column lets it traverse those orders in newest-first order.

Conceptual index lookup: 2,000,000 orders in the table (many different customer IDs and order dates) → Index: (customer_id, created_at DESC) — find customer 12345, then traverse their newest orders → first 20 matching entries. No need to sort all customer orders separately when this index plan is used.

A suitable index can let PostgreSQL retrieve the requested orders efficiently without changing which orders qualify.

It isn't guaranteed to choose that index, however. The planner considers table size, statistics, data distribution and estimated costs.

3. Which solution would we choose?

| Approach | Advantage | Trade-off |
|---|---|---|
| Add a 30-day filter | May reduce eligible rows | Excludes older orders and may still scan extensively |
| Composite index | Can efficiently find the latest 20 for a customer | Consumes storage and increases write overhead |
| Both | Useful if the product explicitly requires recent orders | More complexity and a different result set |

PostgreSQL 18's multicolumn index documentation explains why putting an equality-filtered column first is often effective. Supabase's query optimization guide also recommends aligning indexes with filtering and ordering patterns. (PostgreSQL +1)

Before creating the index, we'd inspect existing indexes and compare execution plans in a safe environment. If we created it in a disposable lab, rollback would be:

```sql
drop index if exists public.orders_customer_created_idx;
```

For production, index creation needs a separate operational plan because an ordinary CREATE INDEX can interfere with concurrent writes. We'd consider CREATE INDEX CONCURRENTLY where appropriate, after checking workload and existing indexes.

Your next question: Let's say customer 12345 has 100,000 orders, but the application only wants the latest 20. We create the composite index on (customer_id, created_at DESC).

Do you think PostgreSQL now needs to examine all 100,000 of that customer's orders and sort them, or can it find the first 20 using the index order? Why?

This gets us to the central idea behind B-tree indexes, which is one of the most useful PostgreSQL concepts for a Supabase support interview.

---

**Learner:** well I'm not sure I understand the exact concept, but if you would have the composite index on (customer_id, created_at DESC) than the search query should only pull the results on that one, provided, that the latest update for that index data is very fresh

**Tutor:** You're very close, Kleinkünstler. Your intuition about using the composite index is correct. But there's one important misconception worth fixing:

PostgreSQL indexes are updated as part of database writes. They don't normally need a separate refresh process.

When an application inserts a new order, PostgreSQL updates the relevant index within the same transaction. The index doesn't wait for a scheduled synchronization job.

Let's see how that works.

1. What does a composite B-tree index actually contain?

Imagine we have this index:

```sql
CREATE INDEX orders_customer_created_idx
ON public.orders (customer_id, created_at DESC);
```

Conceptually, its entries are ordered first by customer_id, then by created_at in descending order within each customer.

| customer_id | created_at | Order ID |
|---|---|---|
| 100 | Oct 21, 10:00 | 91 |
| 100 | Oct 20, 15:00 | 88 |
| 100 | Oct 19, 09:00 | 82 |
| 200 | Oct 21, 12:00 | 105 |
| 200 | Oct 18, 11:00 | 79 |
| 300 | Oct 20, 17:00 | 90 |

Conceptual ordering only. A real PostgreSQL B-tree uses internal and leaf pages, with entries that locate table tuples.

Now imagine customer 100 has 100,000 orders.

PostgreSQL can navigate the B-tree to the relevant customer and read entries in newest-first order, stopping once it has obtained the 20 rows required by the query.

It doesn't necessarily have to examine and sort all 100,000 orders.

2. What happens when a new order arrives?

New order inserted (customer 100, October 21 at 14:00) → PostgreSQL updates the table and index within the same transaction → the new order appears in its correct index position. It becomes visible to transactions according to PostgreSQL's MVCC rules.

There is no external indexing service that needs to catch up.

One subtlety: PostgreSQL uses MVCC, so index entries may exist for rows that aren't visible to a particular transaction. PostgreSQL checks visibility and may need to examine additional entries before finding 20 visible rows.

That means an index isn't a guarantee of exactly 20 index-entry reads.

3. How do we verify PostgreSQL actually uses the index?

We would inspect an execution plan:

```sql
EXPLAIN
SELECT id, customer_id, total, created_at
FROM public.orders
WHERE customer_id = 12345
ORDER BY created_at DESC
LIMIT 20;
```

A possible plan is:

```
Limit
  -> Index Scan using orders_customer_created_idx
       on orders
       Index Cond: (customer_id = 12345)
```

This is an illustrative plan, not a result I've executed.

Notice what is absent: a separate Sort operation.

The index can provide the desired ordering directly. PostgreSQL's planner may choose another plan if it estimates that to be cheaper. (PostgreSQL +1)

One more subtlety: the index usually helps locate the rows; PostgreSQL may still need to fetch data such as total from the actual table. So the database isn't necessarily answering the entire query exclusively from the index.

4. Your next question

Let's test the indexing concept with a small variation. We have an index: (customer_id, created_at DESC)

Which query would this index generally support more efficiently?

A.
```sql
WHERE customer_id = 12345
ORDER BY created_at DESC
LIMIT 20
```

B.
```sql
WHERE total > 100
ORDER BY created_at DESC
LIMIT 20
```

And why? Hint: Think about which column comes first in the index.

---

**Learner:** i would guess the customer_id, but I do not know where total column should be in this index.

**Tutor:** Correct, Kleinkünstler. Query A is the better match for our index.

And your question about total is exactly where we need to distinguish between finding rows and retrieving columns.

1. Why Query A benefits from our index

Our index is:

```sql
CREATE INDEX orders_customer_created_idx
ON public.orders (customer_id, created_at DESC);
```

It organizes entries primarily by customer_id, and then by created_at within each customer.

| customer_id | created_at ↓ | Location of row |
|---|---|---|
| 100 | Oct 21, 14:00 | Table tuple |
| 100 | Oct 20, 10:00 | Table tuple |
| 100 | Oct 18, 09:00 | Table tuple |
| 200 | Oct 21, 11:00 | Table tuple |
| 200 | Oct 19, 16:00 | Table tuple |

For Query A:

```sql
SELECT *
FROM orders
WHERE customer_id = 12345
ORDER BY created_at DESC
LIMIT 20;
```

PostgreSQL can navigate to customer 12345's section of the index, walk through the newest entries, and stop when it has found 20 visible matching rows.

For Query B:

```sql
SELECT *
FROM orders
WHERE total > 100
ORDER BY created_at DESC
LIMIT 20;
```

The index is far less helpful. It is primarily organized by customer ID, but this query doesn't filter by customer.

Even though created_at is in the index, the entries are not globally sorted by date across every customer.

2. Where does the total column come from?

The total column still exists in the original orders table.

An index doesn't replace the table. It helps PostgreSQL locate the relevant rows.

For example:

```sql
SELECT id, customer_id, total, created_at
FROM orders
WHERE customer_id = 12345
ORDER BY created_at DESC
LIMIT 20;
```

PostgreSQL can:

- Find customer 12345's newest orders through the index.
- Fetch the corresponding table rows.
- Read the id and total values from those rows.

You don't necessarily need total inside the index at all.

There is, however, an optimization called a covering index:

```sql
CREATE INDEX orders_customer_created_idx
ON public.orders (customer_id, created_at DESC)
INCLUDE (id, total);
```

Here:

- customer_id and created_at are index key columns used for searching and ordering.
- id and total are included payload columns, available for retrieving values but not used to determine index order.

Under suitable visibility conditions, PostgreSQL may then perform an Index Only Scan without fetching every corresponding table row. This is not guaranteed, and the larger index adds storage and write costs. (PostgreSQL +1)

We wouldn't create this larger index automatically. We'd first inspect existing indexes and execution plans.

3. Let's test your understanding

Consider this index: (customer_id, created_at DESC). A query asks for:

```sql
SELECT id, total
FROM orders
WHERE customer_id = 12345
ORDER BY created_at DESC
LIMIT 20;
```

One question: Does total need to be in the index for PostgreSQL to use that index to find the latest 20 orders, or can it retrieve total from the original table afterward?

You already have most of the answer.

---

**Learner:** no and we should be able to retreive the total based on the id

**Tutor:** Correct, Kleinkünstler. PostgreSQL can use the index to locate the relevant orders and then retrieve total from the original table.

One small correction: it doesn't necessarily look up the row using id.

A normal PostgreSQL B-tree index contains references to physical table locations, called tuple identifiers (TIDs).

B-tree index (customer_id = 12345, created_at = newest first, TID → physical table location) → follow tuple reference → Orders table (heap: id · customer_id · created_at · total) → read the required values.

So the execution works approximately like this:

- The index finds customer 12345's newest orders.
- PostgreSQL follows the matching tuple references to the table.
- It retrieves id and total.
- It returns the 20 requested orders.

The important distinction:

- Index Scan: Uses the index to find rows, then may fetch columns from the table.
- Index Only Scan: May retrieve all requested columns directly from the index, subject to PostgreSQL's visibility checks.

Reference: PostgreSQL — Index-Only Scans.

Next: an actual performance troubleshooting decision. Suppose our customer creates the composite index, but their query is still slow. An execution plan shows:

```
Index Scan using orders_customer_created_idx
  Index Cond: (customer_id = 12345)

Execution Time: 1800 ms
```

The index is being used, yet execution takes 1.8 seconds.

What's the next thing you'd investigate?

Think about what could make a query slow even when PostgreSQL has found a suitable index.

---

**Learner:** so what else is the query requesting? if the customer with that id has a lot of orders, what else are we searching for? and how often

**Tutor:** Good thinking, Kleinkünstler. You're asking two important questions:

- What else does the query actually do? Having an index doesn't guarantee every part of the operation is efficient.
- How often does the query execute? A query taking 1.8 seconds once is a different operational problem from one taking 1.8 seconds hundreds of times per minute.

And you're right to question how many orders this customer has.

However, remember our query:

```sql
SELECT id, customer_id, total, created_at
FROM public.orders
WHERE customer_id = 12345
ORDER BY created_at DESC
LIMIT 20;
```

With a suitable (customer_id, created_at DESC) index, PostgreSQL should generally be able to find 20 qualifying visible rows without processing all 100,000 of that customer's orders.

So 1.8 seconds is suspicious, but the index scan alone doesn't tell us where the time went.

What we'd inspect next. Our fictional execution plan only told us:

```
Index Scan using orders_customer_created_idx
Execution Time: 1800 ms
```

That's not enough detail to explain the delay.

I'd ask for an execution plan with buffer statistics:

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, customer_id, total, created_at
FROM public.orders
WHERE customer_id = 12345
ORDER BY created_at DESC
LIMIT 20;
```

This actually executes the SELECT, so we'd run it deliberately, preferably in a safe test environment or under appropriate production safeguards.

The output helps distinguish several possibilities:

| Observation | Possible explanation |
|---|---|
| Many shared hit blocks | A lot of data accessed from PostgreSQL's buffer cache |
| Many shared read blocks | Blocks needed to be read into the buffer cache |
| Many rows scanned but rejected | Inefficient filtering, potentially RLS |
| Few rows and few buffers, but long runtime | Investigate waits, I/O timing and other execution overhead |
| Fast query execution, slow API response | Investigate application, network, connection waiting or response handling |

PostgreSQL's documentation explains these counters in detail: EXPLAIN and BUFFERS. (PostgreSQL +1)

Important: PostgreSQL's EXPLAIN ANALYZE execution time is not the same as end-to-end HTTP response time. It excludes network transmission to the client. (PostgreSQL)

Let's make this concrete. The customer provides another fictional result:

```
Limit
  -> Index Scan using orders_customer_created_idx
       Index Cond: (customer_id = 12345)
       Buffers: shared hit=120, read=8500

Execution Time: 1800 ms
```

This is interesting: the query uses the index, but it also needs to read a large number of database blocks.

That suggests investigating disk reads, cache behavior, and why an apparently simple LIMIT 20 query accesses so many blocks. A buffer read count alone doesn't establish that storage I/O caused all 1.8 seconds.

Your next question: Why might PostgreSQL need to examine thousands of index or table pages even though the query only returns 20 orders?

Hint: Finding an index entry is not necessarily the same as finding a row that the current transaction is allowed to see.
