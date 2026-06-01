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
    """Create tables, then add auction columns to legacy SQLite DBs."""
    await conn.run_sync(Base.metadata.create_all)

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


async def init_db() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await run_migrations(conn)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    factory = get_session_factory()
    async with factory() as session:
        yield session
