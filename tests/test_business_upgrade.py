"""
Integration tests for the "Start selling" upgrade (POST /api/auth/business/upgrade).

An existing non-selling account (student or individual) creates a Business org
it owns and gains is_seller — WITHOUT changing account_type. Exercised through
the real ASGI app; the client's cookie jar carries the session set by login.
"""

import uuid

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.models.user import User

UNIVERSITY_TYPE_ID = uuid.UUID("22222222-0000-4000-8000-000000000001")


async def _seed_org(db: AsyncSession, official_name: str, short_name: str, slug: str, state: str) -> Organization:
    org = Organization(
        id=uuid.uuid4(),
        organization_type_id=UNIVERSITY_TYPE_ID,
        official_name=official_name,
        short_name=short_name,
        slug=slug,
        country="Nigeria",
        state=state,
        status="active",
    )
    db.add(org)
    await db.commit()
    return org


async def _signup_and_login(
    client: AsyncClient, *, role: str, username: str, email: str, **extra
) -> None:
    """Create an account then log in, leaving the session cookie in the client's
    jar so subsequent authenticated calls are authorized."""
    payload = {
        "role": role,
        "full_name": f"{username} test",
        "username": username,
        "email": email,
        "password": "password123",
        **extra,
    }
    r = await client.post("/api/auth/signup", json=payload)
    assert r.status_code == 201, r.text
    r = await client.post(
        "/api/auth/login", json={"identifier": username, "password": "password123"}
    )
    assert r.status_code == 200, r.text


async def test_upgrade_requires_authentication(client: AsyncClient):
    r = await client.post(
        "/api/auth/business/upgrade",
        json={"business_name": "Anon Store", "state": "Lagos"},
    )
    assert r.status_code == 401


async def test_individual_upgrade_flips_is_seller_and_creates_org(db, client: AsyncClient):
    await _signup_and_login(client, role="individual", username="upind", email="upind@example.com")

    r = await client.post(
        "/api/auth/business/upgrade",
        json={"business_name": "Ind Store", "state": "Lagos"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user"]["is_seller"] is True
    # account_type stays what it was — a capability gain, not a persona change.
    assert body["user"]["account_type"] == "individual"
    assert body["organization_id"] is not None

    user = (
        await db.execute(sa.select(User).where(User.username_normalized == "upind"))
    ).scalar_one()
    owned = (
        await db.execute(sa.select(Organization).where(Organization.owner_user_id == user.id))
    ).scalars().first()
    assert owned is not None
    assert owned.official_name == "Ind Store"
    # An individual had no affiliation, so the new business becomes it.
    assert str(owned.id) == body["user"]["organization_id"]


async def test_student_upgrade_keeps_school_as_affiliation(db, client: AsyncClient):
    """A student who starts selling stays a student, keeps their school as
    organization_id, and the owned business is a SEPARATE org."""
    org = await _seed_org(db, "University of Lagos", "UNILAG", "unilag", "Lagos")
    await _signup_and_login(
        client, role="student", username="upstu", email="upstu@example.com",
        organization_id=str(org.id),
    )

    r = await client.post(
        "/api/auth/business/upgrade",
        json={"business_name": "Campus Snacks", "state": "Lagos"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user"]["account_type"] == "student"
    assert body["user"]["is_seller"] is True
    # organization_id stays the SCHOOL, not the new business.
    assert body["user"]["organization_id"] == str(org.id)
    assert body["organization_id"] != str(org.id)


async def test_upgrade_twice_conflicts(db, client: AsyncClient):
    await _signup_and_login(client, role="individual", username="uptwice", email="uptwice@example.com")

    r1 = await client.post(
        "/api/auth/business/upgrade",
        json={"business_name": "First Biz", "state": "Lagos"},
    )
    assert r1.status_code == 200, r1.text

    r2 = await client.post(
        "/api/auth/business/upgrade",
        json={"business_name": "Second Biz", "state": "Lagos"},
    )
    assert r2.status_code == 409, r2.text

    # Only one owned org exists.
    user = (
        await db.execute(sa.select(User).where(User.username_normalized == "uptwice"))
    ).scalar_one()
    count = (
        await db.execute(
            sa.select(sa.func.count()).select_from(Organization).where(
                Organization.owner_user_id == user.id
            )
        )
    ).scalar()
    assert count == 1
