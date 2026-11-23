"""
Async database engine and session management.

FastAPI's routes here are already `async def` (see app/routers/pages.py),
so the ORM layer uses SQLAlchemy 2.x's async engine + asyncpg driver end
to end, per PRD Ch.12 sec 2 (SQLAlchemy 2.x) and sec 9 (transactions).
"""

import ssl
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings

settings = get_settings()


# Modes where the certificate itself is checked, not just its presence.
_VERIFYING_SSL_MODES = frozenset({"verify-ca", "verify-full"})


def _verifying_ssl_context(mode: str) -> ssl.SSLContext:
    """An SSLContext that verifies the server against Supabase's own root CA.

    asyncpg would accept the string "verify-full" directly, but its string modes
    follow libpq and look for `~/.postgresql/root.crt` — a path that usually does
    not exist, which fails with "root certificate file ... does not exist" and
    says nothing about the certificate. Building the context here points at the
    CA we actually intend to trust.

    `cafile=` (not `create_default_context()` plus `load_default_certs()`) is
    deliberate: it trusts Supabase's root and nothing else, so a certificate from
    any public CA cannot impersonate the pooler either. That is narrower than
    libpq's own verify-full, and narrower is the right direction for the one
    connection holding every user's data.
    """
    cafile = settings.DB_SSL_CA_FILE
    if not cafile:
        raise RuntimeError(
            f"DB_SSL={mode} requires DB_SSL_CA_FILE to point at Supabase's root "
            "certificate (prod-ca-2021.crt). Without it the connection would "
            "encrypt but not verify, which is DB_SSL=require. Download the "
            "certificate from Supabase Dashboard -> Database settings -> SSL "
            "Configuration, or set DB_SSL=require."
        )
    path = Path(cafile)
    if not path.is_file():
        raise RuntimeError(
            f"DB_SSL_CA_FILE={cafile} does not exist. Point it at "
            "prod-ca-2021.crt, or set DB_SSL=require."
        )

    context = ssl.create_default_context(cafile=str(path))
    # CERT_REQUIRED is already create_default_context's default; it is set again
    # because this function's whole purpose is that it is never quietly relaxed.
    context.verify_mode = ssl.CERT_REQUIRED
    # verify-ca checks the chain but not that the certificate belongs to the host
    # we dialled; verify-full checks both. Kept as a real distinction rather than
    # collapsing them, since the host is the part a MITM would get wrong.
    context.check_hostname = mode == "verify-full"
    return context


def connect_args_for(url: str) -> dict:
    """Dialect-specific `connect_args`, for every engine this project builds.

    One definition on purpose: the app engine and Alembic's migration engine are
    two separate `create_async_engine` calls, and a TLS requirement added to only
    one of them is a requirement that migrates in the clear. `migrations/env.py`
    imports this rather than describing its own.

    SQLite gets `check_same_thread=False` because the test suite shares one
    in-memory connection across tasks. Postgres gets `ssl` from DB_SSL, default
    "require" — see the comment on that setting for why TLS is the default rather
    than something you have to remember to turn on.
    """
    if url.startswith("sqlite"):
        return {"check_same_thread": False}
    if settings.DB_SSL in _VERIFYING_SSL_MODES:
        return {"ssl": _verifying_ssl_context(settings.DB_SSL)}
    return {"ssl": settings.DB_SSL}


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
            connect_args=connect_args_for(settings.DATABASE_URL),
        )
    return create_async_engine(
        settings.DATABASE_URL,
        echo=settings.DB_ECHO,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_pre_ping=True,
        connect_args=connect_args_for(settings.DATABASE_URL),
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
