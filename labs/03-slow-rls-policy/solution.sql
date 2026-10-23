-- Lab 03 solution: evaluate the policy's functions once per query, not once per row.
-- Supabase docs, "Call functions with select": wrap auth.uid(), auth.jwt() and security definer functions in
-- (select ...) so the planner caches the result per statement (an initPlan) instead of calling it per row.
-- https://supabase.com/docs/guides/database/postgres/row-level-security.md#call-functions-with-select
-- https://supabase.com/docs/guides/troubleshooting/rls-performance-and-best-practices-Z5Jjwv.md

-- Before (on Saru's Mac): ~11.6 s for the page (times out at 5 s); with an index on user_id: unchanged.
alter policy orders_visible on lab03.orders
  using ((select auth.uid()) = user_id or (select lab03.is_support_agent()));
-- After: ~35 ms. The plan shows two InitPlans; the Seq Scan Filter compares with their results.
-- An index on user_id still cannot be used for an OR with a non-indexable term; for customers you could
-- split the policy (one for owners, one for agents), each then simple enough for its own plan.
