import aiosqlite

DB_NAME = "bot.db"


async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                link_enabled INTEGER NOT NULL DEFAULT 1,
                disabled_until INTEGER
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS anonymous_messages (
                recipient_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                sender_id INTEGER NOT NULL,
                PRIMARY KEY (recipient_id, message_id)
            )
        """)

        await db.commit()

async def add_user(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            """
            INSERT OR IGNORE INTO users (user_id)
            VALUES (?)
            """,
            (user_id,)
        )

        await db.commit()

import time

async def save_anonymous_message(
    recipient_id: int,
    message_id: int,
    sender_id: int
):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            """
            INSERT OR REPLACE INTO anonymous_messages
            (recipient_id, message_id, sender_id)
            VALUES (?, ?, ?)
            """,
            (recipient_id, message_id, sender_id)
        )

        await db.commit()

async def get_anonymous_sender(
    recipient_id: int,
    message_id: int
):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            """
            SELECT sender_id
            FROM anonymous_messages
            WHERE recipient_id = ? AND message_id = ?
            """,
            (recipient_id, message_id)
        )

        row = await cursor.fetchone()

        if row is None:
            return None

        return row[0]

async def get_link_status(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            """
            SELECT link_enabled, disabled_until
            FROM users
            WHERE user_id = ?
            """,
            (user_id,)
        )

        row = await cursor.fetchone()

        if row is None:
            return None, None

        link_enabled, disabled_until = row

        if link_enabled:
            return True, None

        if disabled_until is None:
            return False, None

        now = int(time.time())

        if disabled_until <= now:
            await db.execute(
                """
                UPDATE users
                SET link_enabled = 1,
                    disabled_until = NULL
                WHERE user_id = ?
                """,
                (user_id,)
            )
            await db.commit()

            return True, None

        return False, disabled_until


async def disable_link(user_id: int, seconds: int | None = None):
    disabled_until = None

    if seconds is not None:
        disabled_until = int(time.time()) + seconds

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            """
            UPDATE users
            SET link_enabled = 0,
                disabled_until = ?
            WHERE user_id = ?
            """,
            (disabled_until, user_id)
        )

        await db.commit()


async def enable_link(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            """
            UPDATE users
            SET link_enabled = 1,
                disabled_until = NULL
            WHERE user_id = ?
            """,
            (user_id,)
        )

        await db.commit()