1. More CPU did not help. Before changing anything, what does `explain (analyze, buffers)` say PostgreSQL actually did?
2. Look at the lowest plan node: how many rows did it read, and how many did the filter remove?
3. The query filters on one column and orders by another. Which existing index could serve either? (`pg_indexes`)
4. Try an index on `customer_unique_id` alone. Is the Sort node gone? Why not?
5. An index on `(customer_unique_id, order_purchase_timestamp desc)` hands rows over already in page order; LIMIT 20 can stop early. Compare the plan and time before and after.
