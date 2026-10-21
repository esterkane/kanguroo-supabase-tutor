-- Lab 01: the policy is correct, the GRANT is missing. Symptom: 42501 before RLS runs.
drop schema if exists lab01 cascade;
create schema lab01;
grant usage on schema lab01 to anon, authenticated;

create table lab01.orders (
  id        bigint generated always as identity primary key,
  user_id   uuid not null,
  total     numeric(10,2) not null,
  created_at timestamptz not null default now()
);
create index on lab01.orders (user_id);

insert into lab01.orders (user_id, total)
select case when g % 2 = 0 then '11111111-1111-1111-1111-111111111111'::uuid
            else '22222222-2222-2222-2222-222222222222'::uuid end,
       (random() * 100)::numeric(10,2)
from generate_series(1, 20) g;

alter table lab01.orders enable row level security;

-- The policy is fine.
create policy orders_owner_select on lab01.orders
  for select to authenticated
  using ((select auth.uid()) = user_id);

-- The defect: nobody granted SELECT on the table to `authenticated`.
-- (intentionally no `grant select on lab01.orders to authenticated;`)
