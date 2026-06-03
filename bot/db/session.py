from collections.abc import AsyncGenerator
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.config import get_settings
from bot.db.models import Base

_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None

_LISTING_COLUMNS = [
    ("kind", "VARCHAR(16) NOT NULL DEFAULT 'sale'"),
    ("start_price", "FLOAT"),
    ("min_bid_step", "FLOAT"),
    ("ends_at", "DATETIME"),
    ("high_bidder_id", "BIGINT"),
]

_USER_COLUMNS = [
    ("successful_deals", "INTEGER NOT NULL DEFAULT 0"),
]


def get_engine():
    global _engine, _session_factory
    if _engine is None:
        settings = get_settings()
        db_url = settings.database_url
        if db_url.startswith("sqlite"):
            path = db_url.split("///")[-1]
            if path and path != ":memory:":
                Path(path).parent.mkdir(parents=True, exist_ok=True)
        _engine = create_async_engine(db_url, echo=False)
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    get_engine()
    assert _session_factory is not None
    return _session_factory


async def run_migrations(conn) -> None:
    """Create tables, then add missing columns to legacy SQLite DBs."""
    await conn.run_sync(Base.metadata.create_all)

    user_result = await conn.execute(text("PRAGMA table_info(users)"))
    user_rows = user_result.fetchall()
    existing_user_columns = {row[1] for row in user_rows}
    for name, ddl in _USER_COLUMNS:
        if name not in existing_user_columns:
            await conn.execute(text(f"ALTER TABLE users ADD COLUMN {name} {ddl}"))

    result = await conn.execute(text("PRAGMA table_info(listings)"))
    rows = result.fetchall()
    if not rows:
        return

    existing = {row[1] for row in rows}
    for name, ddl in _LISTING_COLUMNS:
        if name not in existing:
            await conn.execute(text(f"ALTER TABLE listings ADD COLUMN {name} {ddl}"))

    await conn.execute(
        text(
            """
            UPDATE listings
            SET kind = 'auction'
            WHERE start_price IS NOT NULL
              AND min_bid_step IS NOT NULL
              AND ends_at IS NOT NULL
              AND (kind IS NULL OR kind IN ('sale', 'SALE'))
            """
        )
    )

    await conn.execute(
        text(
            """
            UPDATE users
            SET successful_deals =
                (
                    SELECT COUNT(*)
                    FROM listings AS listing_sales
                    WHERE listing_sales.seller_id = users.telegram_id
                      AND LOWER(listing_sales.status) = 'sold'
                      AND (
                          LOWER(COALESCE(listing_sales.kind, 'sale')) = 'auction'
                          OR (
                              LOWER(COALESCE(listing_sales.kind, 'sale')) = 'sale'
                              AND NOT EXISTS (
                                  SELECT 1
                                  FROM listing_items AS existing_items
                                  WHERE existing_items.listing_id = listing_sales.id
                              )
                          )
                      )
                )
                +
                (
                    SELECT COUNT(*)
                    FROM listing_items AS sold_items
                    JOIN listings AS item_listings
                      ON item_listings.id = sold_items.listing_id
                    WHERE item_listings.seller_id = users.telegram_id
                      AND LOWER(sold_items.status) = 'sold'
                )
            """
        )
    )


async def init_db() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await run_migrations(conn)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    factory = get_session_factory()
    async with factory() as session:
        yield session
