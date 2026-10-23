1. Start with the token, not the policy: as `authenticated` with the customer's `sub`, what does `auth.uid()` return, and which profile row do you see?
2. The token is right. So which predicate decides what "my orders" means? Read `qual` in `pg_policies`.
3. As postgres, count this customer's orders and their distinct `customer_id` values. What does that tell you about `customer_id` in this dataset?
4. One person, 17 `customer_id`s: the profile stored the first one, the policy compares with exactly that one. Which column identifies the person?
5. Change the policy to compare `customer_unique_id` with the profile's `customer_unique_id` (keep `(select auth.uid())`), then repeat the reproduce query and try a second customer's sub.
