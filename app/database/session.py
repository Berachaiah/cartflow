"""
Async database engine and session management.

FastAPI's routes here are already `async def` (see app/routers/pages.py),
so the ORM layer uses SQLAlchemy 2.x's async engine + asyncpg driver end
to end, per PRD Ch.12 sec 2 (SQLAlchemy 2.x) and sec 9 (transactions).
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings

settings = get_settings()


def _build_engine() -> AsyncEngine:
    """Create the async engine for the configured DATABASE_URL.

    Postgres (asyncpg, the production/Supabase target) uses a real connection
    pool. SQLite — used only by the test suite (sqlite+aiosqlite) — cannot
    accept `pool_size`/`max_overflow` (its async pool is a StaticPool), so we
    branch on the dialect. An in-memory SQLite URL additionally needs a single
    shared connection (StaticPool) so the schema created in one session is
    visible to the next.
    """
    if settings.DATABASE_URL.startswith("sqlite"):
        return create_async_engine(
            settings.DATABASE_URL,
            echo=settings.DB_ECHO,
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
    return create_async_engine(
        settings.DATABASE_URL,
        echo=settings.DB_ECHO,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_pre_ping=True,
    )


engine: AsyncEngine = _build_engine()

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields a session, commits on success, rolls back on error.

    Usage:
        @router.get("/products")
        async def list_products(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def session_scope() -> AsyncGenerator[AsyncSession, None]:
    """Context-manager variant for use outside request handlers
    (background jobs, scripts, startup tasks).
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def dispose_engine() -> None:
    """Call on application shutdown to cleanly close the connection pool."""
    await engine.dispose()
