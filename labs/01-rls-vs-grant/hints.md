1. The message says *permission denied*, not *0 rows*. Which of the two authorization layers produces that exact SQLSTATE?
2. RLS only filters rows the role is already allowed to read. What must be true before any policy is even evaluated?
3. Run `\dp lab01.orders` (or query `information_schema.role_table_grants` for `lab01.orders`). Who holds SELECT?
4. Compare with a table that works for `authenticated`. What is different in the privilege column?
5. Grant the missing object privilege, re-run the evidence query, and explain why you now get 10 rows and not 20.
