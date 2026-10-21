-- BEFORE: expect SQLSTATE 42501 "permission denied for table orders"
begin;
set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"11111111-1111-1111-1111-111111111111","role":"authenticated"}', true);
select * from lab01.orders;   -- 42501
rollback;

-- FIX: object privilege first; RLS continues to limit rows.
grant select on lab01.orders to authenticated;

-- AFTER: expect 10 rows (only user 1111...'s orders), not 20
begin;
set local role authenticated;
select set_config('request.jwt.claims', '{"sub":"11111111-1111-1111-1111-111111111111","role":"authenticated"}', true);
select count(*) from lab01.orders;   -- 10
rollback;

-- MECHANISM: GRANT answers "may this role touch this object at all?" (42501 if not).
-- RLS answers "which rows?" and only runs if the GRANT check passed. Two separate controls.
