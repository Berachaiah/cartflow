"""
Test fixtures and configuration.

Provides an async test harness on sqlite+aiosqlite (app models are
dialect-agnostic) with an in-memory DB that's recreated per-test, plus an
ASGI test client that exercises the real FastAPI app via `httpx.ASGITransport`.

Usage:
    async def test_signup(db: AsyncSession, client: AsyncClient):
        # `db` is a fresh SQLite session; `client` calls the real ASGI app.
        # Taxonomy is seeded; build test orgs/users as needed.
        ...
"""

import os
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

# Set DATABASE_URL to SQLite BEFORE importing app modules (session.py reads config).
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

from app.database.base import Base
from app.database.session import get_db
from app.main import app
from app.models.organization import OrganizationGroup, OrganizationType

# Deterministic taxonomy IDs mirror the migration (0002_organizations.py)
EDU_GROUP_ID = uuid.UUID("11111111-0000-4000-8000-000000000001")
UNIVERSITY_TYPE_ID = uuid.UUID("22222222-0000-4000-8000-000000000001")
# Business group + its default SME type — the multi-persona signup (brand /
# student_business) resolves new businesses to the SME type within this group.
BUSINESS_GROUP_ID = uuid.UUID("11111111-0000-4000-8000-000000000002")
SME_TYPE_ID = uuid.UUID("22222222-0000-4000-8000-000000000012")


@pytest_asyncio.fixture
async def engine():
    """Shared in-memory SQLite engine (StaticPool keeps one connection for :memory:)."""
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Seed the minimal taxonomy every test needs (Education + Business groups
    # and their default types). Business/SME is required by the brand and
    # student_business signup roles, which resolve new orgs to the SME type.
    SessionLocal = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    async with SessionLocal() as s:
        s.add(OrganizationGroup(id=EDU_GROUP_ID, name="Education", slug="education", sort_order=1))
        s.add(OrganizationGroup(id=BUSINESS_GROUP_ID, name="Business", slug="business", sort_order=2))
        await s.flush()
        s.add(
            OrganizationType(
                id=UNIVERSITY_TYPE_ID,
                organization_group_id=EDU_GROUP_ID,
                name="University",
                slug="university",
                sort_order=1,
            )
        )
        s.add(
            OrganizationType(
                id=SME_TYPE_ID,
                organization_group_id=BUSINESS_GROUP_ID,
                name="SME",
                slug="sme",
                sort_order=2,
            )
        )
        await s.commit()

    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db(engine):
    """Fresh async session for each test."""
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
    async with SessionLocal() as session:
        yield session
        await session.rollback()  # Clean up any uncommitted changes


@pytest_asyncio.fixture
async def client(engine):
    """ASGI test client with dependency override to use the test DB."""
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)

    async def _get_test_db():
        async with SessionLocal() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _get_test_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    app.dependency_overrides.clear()
