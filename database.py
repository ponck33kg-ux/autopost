import asyncpg
import os
from typing import Optional

_pool = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        dsn = os.getenv("DATABASE_URL") or (
            f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
            f"@{os.getenv('DB_HOST')}/{os.getenv('DB_NAME')}"
        )
        _pool = await asyncpg.create_pool(dsn, ssl="require", min_size=2, max_size=10)
    return _pool


async def init_db():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS seen_urls (
                url          TEXT NOT NULL,
                channel_name TEXT NOT NULL,
                seen_at      TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (url, channel_name)
            );

            CREATE TABLE IF NOT EXISTS drafts (
                id                     SERIAL PRIMARY KEY,
                channel_name           TEXT NOT NULL,
                channel_chat_id        TEXT NOT NULL,
                moderation_message_id  BIGINT UNIQUE,
                title                  TEXT,
                content                TEXT NOT NULL,
                source_url             TEXT,
                status                 TEXT DEFAULT 'pending',
                created_at             TIMESTAMPTZ DEFAULT NOW()
            );
        """)


# ── seen_urls ──────────────────────────────────────────────────────────────────

async def is_url_seen(url: str, channel_name: str) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT 1 FROM seen_urls WHERE url = $1 AND channel_name = $2",
            url, channel_name,
        )
        return row is not None


async def mark_url_seen(url: str, channel_name: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO seen_urls (url, channel_name) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            url, channel_name,
        )


# ── drafts ─────────────────────────────────────────────────────────────────────

async def save_draft(
    channel_name: str,
    channel_chat_id: str,
    title: str,
    content: str,
    source_url: str,
) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO drafts (channel_name, channel_chat_id, title, content, source_url)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
            """,
            channel_name, channel_chat_id, title, content, source_url,
        )
        return row["id"]


async def set_moderation_message_id(draft_id: int, message_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE drafts SET moderation_message_id = $1 WHERE id = $2",
            message_id, draft_id,
        )


async def get_draft_by_message_id(message_id: int) -> Optional[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM drafts WHERE moderation_message_id = $1",
            message_id,
        )
        return dict(row) if row else None


async def get_draft_by_id(draft_id: int) -> Optional[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM drafts WHERE id = $1",
            draft_id,
        )
        return dict(row) if row else None


async def update_draft_content(draft_id: int, content: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE drafts SET content = $1, status = 'edited' WHERE id = $2",
            content, draft_id,
        )


async def update_draft_status(draft_id: int, status: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE drafts SET status = $1 WHERE id = $2",
            status, draft_id,
        )
