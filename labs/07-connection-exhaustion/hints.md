1. "Bigger instance" assumes the server is full. Compare `max_connections` with how many connections exist right now. Which limit does the error message name?
2. A role can have its own limit. What is `rolconnlimit` for `lab07_app`, and how many sessions does it have open?
3. Look at those sessions: `state`, `state_change`, `query`. Are they working, or waiting for a client that forgot them?
4. Right now: end the leaked sessions (one `pg_terminate_backend(pid)` per statement) and reproduce again. Why does restarting the API look like a fix, and why is it not a root cause?
5. Server side: `idle_session_timeout` can be set for one role (`alter role lab07_app set idle_session_timeout = '1min'`, persist it); new connections get it. App side: release clients to a pool, or connect through Supavisor in transaction mode. Reproduce once more and read `session_settings`.
