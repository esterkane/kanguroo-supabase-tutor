-- Passes when autovacuum is allowed again and the dead row versions have been vacuumed.
begin;
select plan(2);

select ok(coalesce((select array_to_string(reloptions, ',') from pg_class
                    where oid = 'lab06.orders'::regclass), '') !~ 'autovacuum_enabled=(false|off)',
          'autovacuum is enabled for lab06.orders');

-- VACUUM marks pages all-visible once no dead tuples are left on them; this is updated transactionally.
select ok((select relallvisible >= 0.9 * (pg_relation_size(oid) / current_setting('block_size')::int)
           from pg_class where oid = 'lab06.orders'::regclass),
          'the table has been vacuumed: at least 90 % of its pages are all-visible');

select * from finish();
rollback;
