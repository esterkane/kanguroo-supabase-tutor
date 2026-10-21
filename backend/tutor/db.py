"""Database helpers for user-scoped access.

User tables are read and written as the `authenticated` role with the user's JWT claims set, exactly
as PostgREST does per request, so RLS policies are the authority, not application code.
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool


@asynccontextmanager
async def as_user(pool: AsyncConnectionPool, user_id: UUID) -> AsyncIterator[AsyncConnection]:
    """A transaction running as `authenticated` with `request.jwt.claims.sub = user_id`."""
    claims = json.dumps({"sub": str(user_id), "role": "authenticated"})
    async with pool.connection() as conn, conn.transaction():
        await conn.execute("set local role authenticated")
        await conn.execute("select set_config('request.jwt.claims', %s, true)", (claims,))
        yield conn
