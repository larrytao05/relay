"""Database authorization and locking for durable canvas writes."""

from uuid import UUID

import asyncpg


async def lock_canvas_write_access(
    conn: asyncpg.Connection,
    canvas_id: UUID,
    user_id: UUID,
    token_hash: str,
) -> int | None:
    session = await conn.fetchrow(
        """
        SELECT auth_session.user_id
        FROM auth_session
        JOIN canvas_member ON canvas_member.user_id = auth_session.user_id
        WHERE auth_session.token_hash = $1
          AND auth_session.user_id = $2
          AND canvas_member.canvas_id = $3
          AND auth_session.expires_at > now()
        FOR KEY SHARE OF auth_session
        """,
        token_hash,
        user_id,
        canvas_id,
    )
    if session is None:
        return None

    canvas = await conn.fetchrow(
        "SELECT revision FROM canvas WHERE id = $1 FOR UPDATE",
        canvas_id,
    )
    return canvas["revision"] if canvas is not None else None
