-- Passes when the history matches the repo and production matches what the migrations describe.
begin;
select plan(4);

select is((select count(*)::int from lab08.migration_list() where local is null or remote is null), 0,
          'every repo migration is recorded remotely, and nothing else is');
select is((select data_type from information_schema.columns
           where table_schema = 'lab08' and table_name = 'orders' and column_name = 'delivery_eta'),
          'timestamp with time zone', 'delivery_eta has the type the migration defines');
select is((select count(*)::int from lab08.orders where delivery_eta is distinct from order_estimated_delivery_date), 0,
          'delivery_eta holds Olist''s estimated delivery date, not the hotfix guess');
select has_view('lab08', 'late_orders', 'the new migration is deployed');

select * from finish();
rollback;
