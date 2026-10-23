-- Passes only when RLS identifies the person (customer_unique_id) and still isolates customers.
begin;
select plan(4);

create function pg_temp.visible(sub text, q text) returns bigint language plpgsql as $f$
declare n bigint;
begin
  perform set_config('request.jwt.claims', json_build_object('sub', sub, 'role', 'authenticated')::text, true);
  set local role authenticated;
  execute q into n;
  reset role;
  return n;
end $f$;

select is(pg_temp.visible('b83579fb-095b-495e-3c5a-30fd7fcc0b62', 'select count(*) from lab02.orders'), 17::bigint,
          'the 17-order customer sees all 17 orders');
select is(pg_temp.visible('f8cc7da0-408b-5ffd-1f21-6f48d2c5dcbe', 'select count(*) from lab02.orders'), 9::bigint,
          'the 9-order customer sees all 9 orders');
select is(pg_temp.visible('b83579fb-095b-495e-3c5a-30fd7fcc0b62',
          $$select count(*) from lab02.orders where customer_unique_id <> '8d50f5eadf50201ccdcedfb9e2ac8455'$$),
          0::bigint, 'nobody else''s orders are visible');
select is(pg_temp.visible('', 'select count(*) from lab02.orders'), 0::bigint, 'no identity, no rows');

select * from finish();
rollback;
