"""
Integration tests for graduation self-toggle (POST /api/auth/graduation).

graduated_at is set/cleared. Its one behavioural effect: a graduated user who
OWNS a business is asked to review their pickup address (needs_pickup_update).
No badge is set anywhere — the response never exposes an alumni/graduate flag.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization

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


async def test_graduation_requires_authentication(client: AsyncClient):
    r = await client.post("/api/auth/graduation", json={"graduated": True})
    assert r.status_code == 401


async def test_graduate_student_without_business_no_pickup_prompt(db, client: AsyncClient):
    org = await _seed_org(db, "University of Lagos", "UNILAG", "unilag", "Lagos")
    await _signup_and_login(
        client, role="student", username="gradstu", email="gradstu@example.com",
        organization_id=str(org.id),
    )

    r = await client.post("/api/auth/graduation", json={"graduated": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["graduated_at"] is not None
    assert body["needs_pickup_update"] is False
    # No badge/alumni field leaks into the response.
    assert "badge" not in body
    assert "alumni" not in body


async def test_graduate_student_business_prompts_pickup_update(db, client: AsyncClient):
    org = await _seed_org(db, "University of Ibadan", "UI", "ui", "Oyo")
    await _signup_and_login(
        client, role="student_business", username="gradsb", email="gradsb@example.com",
        organization_id=str(org.id), business_name="Grad Store", state="Oyo",
    )

    r = await client.post("/api/auth/graduation", json={"graduated": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["graduated_at"] is not None
    # Owns a business → prompt to review the (likely-stale campus) pickup address.
    assert body["needs_pickup_update"] is True


async def test_ungraduate_clears_timestamp(db, client: AsyncClient):
    org = await _seed_org(db, "University of Lagos", "UNILAG", "unilag", "Lagos")
    await _signup_and_login(
        client, role="student", username="ungrad", email="ungrad@example.com",
        organization_id=str(org.id),
    )

    r = await client.post("/api/auth/graduation", json={"graduated": True})
    assert r.status_code == 200
    assert r.json()["graduated_at"] is not None

    r = await client.post("/api/auth/graduation", json={"graduated": False})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["graduated_at"] is None
    # Un-graduating never asks for a pickup update.
    assert body["needs_pickup_update"] is False
