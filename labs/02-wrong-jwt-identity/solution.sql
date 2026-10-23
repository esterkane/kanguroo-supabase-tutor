-- Lab 02 solution: identify the person, not the order.
-- Olist assigns a new customer_id to every order; customer_unique_id is the person (dataset documentation,
-- kaggle.com/datasets/olistbr/brazilian-ecommerce). The policy compared the per-order key.

-- Before (as authenticated, sub b83579fb-...): 1 row. As postgres: 17 orders, 17 distinct customer_id.
alter policy orders_own on lab02.orders
  using (customer_unique_id = (select p.customer_unique_id from lab02.profiles p where p.user_id = (select auth.uid())));

-- After: 17 rows for b83579fb-095b-495e-3c5a-30fd7fcc0b62, 9 for f8cc7da0-408b-5ffd-1f21-6f48d2c5dcbe.
-- No claims: auth.uid() is NULL, the subquery is NULL, `x = NULL` is not true -> zero rows, never all rows.
-- Docs: auth.uid() returns the ID of the user making the request
-- https://supabase.com/docs/guides/database/postgres/row-level-security.md#helper-functions
