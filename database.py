import asyncpg
import os
from typing import Optional

_pool = None

MAX_CHANNELS_PER_USER = 5


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
            CREATE TABLE IF NOT EXISTS users (
                user_id    BIGINT PRIMARY KEY,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS channels (
                id           SERIAL PRIMARY KEY,
                user_id      BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                chat_id      TEXT NOT NULL,
                name         TEXT NOT NULL,
                topic_id     INTEGER NOT NULL,
                prompt_style TEXT DEFAULT 'деловой',
                max_posts    INTEGER DEFAULT 5,
                created_at   TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS sources (
                id         SERIAL PRIMARY KEY,
                channel_id INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
                url        TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE (channel_id, url)
            );

            CREATE TABLE IF NOT EXISTS seen_urls (
                url        TEXT NOT NULL,
                channel_id INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
                seen_at    TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (url, channel_id)
            );

            CREATE TABLE IF NOT EXISTS drafts (
                id                    SERIAL PRIMARY KEY,
                channel_id            INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
                moderation_message_id BIGINT UNIQUE,
                title                 TEXT,
                content               TEXT NOT NULL,
                source_url            TEXT,
                status                TEXT DEFAULT 'pending',
                created_at            TIMESTAMPTZ DEFAULT NOW()
            );
        """)


# ── users ──────────────────────────────────────────────────────────────────────

async def get_or_create_user(user_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO users (user_id) VALUES ($1) ON CONFLICT DO NOTHING",
            user_id,
        )


# ── channels ───────────────────────────────────────────────────────────────────

async def get_user_channels(user_id: int) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM channels WHERE user_id = $1 ORDER BY created_at",
            user_id,
        )
        return [dict(r) for r in rows]


async def count_user_channels(user_id: int) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT COUNT(*) FROM channels WHERE user_id = $1", user_id
        )


async def add_channel(user_id: int, chat_id: str, name: str, topic_id: int, prompt_style: str) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO channels (user_id, chat_id, name, topic_id, prompt_style)
            VALUES ($1, $2, $3, $4, $5) RETURNING id
            """,
            user_id, chat_id, name, topic_id, prompt_style,
        )
        return row["id"]


async def get_channel(channel_id: int) -> Optional[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM channels WHERE id = $1", channel_id)
        return dict(row) if row else None


async def delete_channel(channel_id: int, user_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM channels WHERE id = $1 AND user_id = $2",
            channel_id, user_id,
        )


# ── sources ────────────────────────────────────────────────────────────────────

async def get_channel_sources(channel_id: int) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM sources WHERE channel_id = $1 ORDER BY created_at",
            channel_id,
        )
        return [dict(r) for r in rows]


async def add_source(channel_id: int, url: str) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            await conn.execute(
                "INSERT INTO sources (channel_id, url) VALUES ($1, $2)",
                channel_id, url,
            )
            return True
        except asyncpg.UniqueViolationError:
            return False


async def delete_source(source_id: int, channel_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM sources WHERE id = $1 AND channel_id = $2",
            source_id, channel_id,
        )


# ── seen_urls ──────────────────────────────────────────────────────────────────

async def is_url_seen(url: str, channel_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT 1 FROM seen_urls WHERE url = $1 AND channel_id = $2",
            url, channel_id,
        )
        return row is not None


async def mark_url_seen(url: str, channel_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO seen_urls (url, channel_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            url, channel_id,
        )


# ── drafts ─────────────────────────────────────────────────────────────────────

async def save_draft(channel_id: int, title: str, content: str, source_url: str) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO drafts (channel_id, title, content, source_url)
            VALUES ($1, $2, $3, $4) RETURNING id
            """,
            channel_id, title, content, source_url,
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
            "SELECT * FROM drafts WHERE moderation_message_id = $1", message_id
        )
        return dict(row) if row else None


async def get_draft_by_id(draft_id: int) -> Optional[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM drafts WHERE id = $1", draft_id)
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
            "UPDATE drafts SET status = $1 WHERE id = $2", status, draft_id
        )