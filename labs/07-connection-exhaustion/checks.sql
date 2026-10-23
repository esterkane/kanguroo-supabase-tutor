-- Passes when the API can connect again and forgotten connections are closed by the server.
begin;
select plan(2);

select ok((select count(*) from pg_stat_activity where usename = 'lab07_app')
          < (select rolconnlimit from pg_roles where rolname = 'lab07_app'),
          'lab07_app has a free connection slot (leaked sessions ended)');
select ok(exists (
  select 1 from pg_roles r, unnest(r.rolconfig) c
  where r.rolname = 'lab07_app' and c like 'idle_session_timeout=%'
    and split_part(c, '=', 2) not in ('0', '0ms', '0s')),
  'idle_session_timeout is set for lab07_app');

select * from finish();
rollback;
