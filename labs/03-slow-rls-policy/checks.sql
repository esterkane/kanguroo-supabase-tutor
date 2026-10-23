-- Passes only when the policy's functions are evaluated once per query and the page fits the timeout.
begin;
select plan(4);

select ok((select qual from pg_policies where schemaname = 'lab03' and tablename = 'orders')
          ~* 'select auth\.uid\(\)', 'auth.uid() is wrapped in a scalar subquery');
select ok((select qual from pg_policies where schemaname = 'lab03' and tablename = 'orders')
          ~* 'select lab03\.is_support_agent\(\)', 'is_support_agent() is wrapped in a scalar subquery');

create function pg_temp.page_rows(sub text, others_only boolean default false) returns bigint language plpgsql as $f$
declare n bigint;
begin
  perform set_config('request.jwt.claims', json_build_object('sub', sub, 'role', 'authenticated')::text, true);
  perform set_config('statement_timeout', '2s', true);
  set local role authenticated;
  select count(*) into n from (select order_id from lab03.orders
    where not others_only or user_id is distinct from sub::uuid
    order by order_purchase_timestamp desc limit 20) t;
  reset role;
  return n;
end $f$;

select is(pg_temp.page_rows('b83579fb-095b-495e-3c5a-30fd7fcc0b62'), 20::bigint,
          'the customer''s page answers within 2 s');
select is(pg_temp.page_rows((select user_id::text from lab03.support_agents order by user_id limit 1), true), 20::bigint,
          'a support agent still sees other customers'' orders');

select * from finish();
rollback;
