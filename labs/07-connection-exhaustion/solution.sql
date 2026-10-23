-- Lab 07 solution (the terminate steps go through the lab runner, one pid per statement).
-- Evidence: max_connections far from reached; rolconnlimit = 5 and 5 idle sessions of lab07_app (orders-api).
-- PostgreSQL docs: CONNECTION LIMIT = how many concurrent connections the role can make; only normal
-- connections count; never enforced for superusers. https://www.postgresql.org/docs/17/sql-createrole.html

-- 1. Mitigation (now): end the leaked idle sessions, e.g.
--    select pg_terminate_backend(<pid>);   -- for each orders-api pid from pg_stat_activity
--    A restart of the API does the same, which is why it "fixes" it: it is a mitigation, not the cause.

-- 2. Prevention in the database, for this role only (PostgreSQL docs suggest applying idle_session_timeout to
--    particular users; pooled connections may not react well to it):
--    https://www.postgresql.org/docs/17/runtime-config-client.html#GUC-IDLE-SESSION-TIMEOUT
alter role lab07_app set idle_session_timeout = '1min';
--    Applies to NEW sessions: existing leaked ones must still be terminated.

-- 3. Permanent fix in the app: reuse connections (a client pool that releases clients after each request), or
--    connect through Supavisor in transaction mode, which shares a small pool of server connections between
--    many clients. https://supabase.com/docs/guides/troubleshooting/supavisor-faq-YyP5tI.md
