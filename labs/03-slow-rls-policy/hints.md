1. The forum fix (an index) did not help. What does plain `explain` of the page query say, as `authenticated`? Which node, which Filter?
2. Run the same query as postgres, which bypasses RLS. If that is fast, what does the policy add to every row?
3. Look at the Filter: two function calls per row, about a million rows. How often does `lab03.is_support_agent()` run, and what does it do each time?
4. Why can an index on `user_id` not serve `auth.uid() = user_id OR lab03.is_support_agent()`? Try it: does the plan change?
5. Wrap each function call in a scalar subquery, `(select auth.uid())` and `(select lab03.is_support_agent())`: PostgreSQL then evaluates each once per query (an InitPlan). Alter the policy and compare the plan and time.
