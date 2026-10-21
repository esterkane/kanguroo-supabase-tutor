1. The sum is too high, not too low. Which rows could be counted more than once?
2. Pick one order that has two items and run the view's join for just that order_id. How many rows come back, and how many payments does it have?
3. A join multiplies rows: n items × m payments per order. Which column in the view needs the items, and which needs the payments?
4. Aggregate each child table to one row per order before joining (CTE or subquery), then join those to orders.
5. `create or replace view` with the same column names and types, then compare `sum(revenue)` with the payments total again.
