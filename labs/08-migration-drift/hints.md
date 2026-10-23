1. The error is about a column that already exists. What does `migration_list()` say about 20261005120000, locally and remotely?
2. The history says "never applied", the table says the column is there. Look at its type and a few values next to `order_estimated_delivery_date`. Is it the column the migration would have created?
3. `migration repair --status applied` writes one row into the history table and nothing else. If you only did that, what would production look like?
4. Make production match the migration first (type and values), or remove the hand-made column so the migration can create it. What does the courier app reading `delivery_eta` need from you meanwhile?
5. Then record 20261005120000 as applied (the repair: one history row), run `db_push()` with persist, and check `migration_list()` and `late_orders`.
