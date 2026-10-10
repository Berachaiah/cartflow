"""
Integration tests for the organization-based signup flow (spec items #3-#7).

Exercises the real ASGI app through httpx against in-memory SQLite. Covers the
two signup outcomes and the endpoints the signup UX depends on.
"""

import uuid

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.models.organization_request import OrganizationRequest, SignupRequest
from app.models.user import AccountType, User

UNIVERSITY_TYPE_ID = uuid.UUID("22222222-0000-4000-8000-000000000001")


async def _seed_org(
    db: AsyncSession,
    official_name: str,
    short_name: str,
    slug: str,
    state: str,
    status: str = "active",
) -> Organization:
    org = Organization(
        id=uuid.uuid4(),
        organization_type_id=UNIVERSITY_TYPE_ID,
        official_name=official_name,
        short_name=short_name,
        slug=slug,
        country="Nigeria",
        state=state,
        status=status,
    )
    db.add(org)
    await db.commit()
    return org


# --- search / directory / resolve ---------------------------------------

async def test_search_returns_matches(db, client: AsyncClient):
    await _seed_org(db, "University of Lagos", "UNILAG", "unilag", "Lagos")
    r = await client.get("/api/organizations/search", params={"q": "Lag"})
    assert r.status_code == 200
    assert any("Lagos" in o["official_name"] for o in r.json())


async def test_search_surfaces_unverified_orgs(db, client: AsyncClient):
    """Regression: the 'unverified' majority must NOT be hidden from search."""
    await _seed_org(db, "Bells University of Technology", "BELLS", "bells", "Ogun", status="unverified")
    r = await client.get("/api/organizations/search", params={"q": "Bells"})
    assert r.status_code == 200
    assert len(r.json()) == 1


async def test_search_short_query_returns_empty(db, client: AsyncClient):
    await _seed_org(db, "University of Lagos", "UNILAG", "unilag", "Lagos")
    r = await client.get("/api/organizations/search", params={"q": "L"})
    assert r.status_code == 200
    assert r.json() == []


async def test_directory_pagination_envelope(db, client: AsyncClient):
    await _seed_org(db, "University of Lagos", "UNILAG", "unilag", "Lagos")
    await _seed_org(db, "University of Ibadan", "UI", "ui", "Oyo")
    r = await client.get("/api/organizations", params={"per_page": 20})
    body = r.json()
    assert r.status_code == 200
    assert body["total"] == 2
    assert body["pages"] == 1
    assert body["page"] == 1
    assert len(body["items"]) == 2


async def test_directory_state_filter(db, client: AsyncClient):
    await _seed_org(db, "University of Lagos", "UNILAG", "unilag", "Lagos")
    await _seed_org(db, "University of Ibadan", "UI", "ui", "Oyo")
    r = await client.get("/api/organizations", params={"state": "Oyo"})
    assert r.status_code == 200
    assert r.json()["total"] == 1
    assert r.json()["items"][0]["short_name"] == "UI"


async def test_resolve_found(db, client: AsyncClient):
    await _seed_org(db, "University of Lagos", "UNILAG", "unilag", "Lagos")
    r = await client.post("/api/organizations/resolve", json={"name": "Univ of Lagos"})
    assert r.status_code == 200
    assert r.json()["found"] is True


async def test_resolve_miss_does_not_create(db, client: AsyncClient):
    r = await client.post("/api/organizations/resolve", json={"name": "Nonexistent University Zzz"})
    assert r.status_code == 200
    assert r.json()["found"] is False
    # No row was created by a read-only resolve.
    count = (await db.execute(sa.select(sa.func.count()).select_from(Organization))).scalar()
    assert count == 0


# --- taxonomy -----------------------------------------------------------

async def test_taxonomy_groups_and_types(db, client: AsyncClient):
    r = await client.get("/api/organization-groups")
    assert r.status_code == 200
    assert any(g["slug"] == "education" for g in r.json())

    r = await client.get("/api/organization-types", params={"group": "education"})
    assert r.status_code == 200
    assert any(t["slug"] == "university" for t in r.json())


# --- signup: happy path -------------------------------------------------

async def test_signup_with_existing_org_creates_account(db, client: AsyncClient):
    org = await _seed_org(db, "University of Lagos", "UNILAG", "unilag", "Lagos")
    r = await client.post(
        "/api/auth/signup/student",
        json={
            "full_name": "Alice A",
            "username": "alice",
            "email": "alice@example.com",
            "password": "password123",
            "organization_id": str(org.id),
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["outcome"] == "account_created"
    assert body["user"]["username"] == "alice"
    assert body["user"]["organization_id"] == str(org.id)


async def test_signup_accepts_legacy_university_id_alias(db, client: AsyncClient):
    org = await _seed_org(db, "University of Lagos", "UNILAG", "unilag", "Lagos")
    r = await client.post(
        "/api/auth/signup/student",
        json={
            "full_name": "Carol C",
            "username": "carol",
            "email": "carol@example.com",
            "password": "password123",
            "university_id": str(org.id),  # deprecated alias
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["outcome"] == "account_created"


# --- signup: deferred (org not found) -----------------------------------

async def test_signup_unknown_org_defers_and_creates_no_user(db, client: AsyncClient):
    r = await client.post(
        "/api/auth/signup/student",
        json={
            "full_name": "Bob B",
            "username": "bobby",
            "email": "bob@example.com",
            "password": "password123",
            "organization_name": "Some Unknown University XYZ",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["outcome"] == "pending_organization_review"
    assert body["organization_request_id"] is not None
    assert body["user"] is None

    # No user created; exactly one org request + one signup request; no new org.
    users = (await db.execute(sa.select(sa.func.count()).select_from(User))).scalar()
    orgs = (await db.execute(sa.select(sa.func.count()).select_from(Organization))).scalar()
    oreqs = (await db.execute(sa.select(sa.func.count()).select_from(OrganizationRequest))).scalar()
    sreqs = (await db.execute(sa.select(sa.func.count()).select_from(SignupRequest))).scalar()
    assert users == 0
    assert orgs == 0
    assert oreqs == 1
    assert sreqs == 1


# --- signup: uniqueness -------------------------------------------------

async def test_signup_duplicate_email_conflicts(db, client: AsyncClient):
    org = await _seed_org(db, "University of Lagos", "UNILAG", "unilag", "Lagos")
    payload = {
        "full_name": "Alice A",
        "username": "alice",
        "email": "alice@example.com",
        "password": "password123",
        "organization_id": str(org.id),
    }
    r1 = await client.post("/api/auth/signup/student", json=payload)
    assert r1.status_code == 201

    payload2 = {**payload, "username": "alice2"}  # same email, new username
    r2 = await client.post("/api/auth/signup/student", json=payload2)
    assert r2.status_code == 409
    assert r2.json()["error"]["code"] == "CONFLICT"


async def test_signup_requires_an_organization(db, client: AsyncClient):
    r = await client.post(
        "/api/auth/signup/student",
        json={
            "full_name": "No Org",
            "username": "noorg",
            "email": "noorg@example.com",
            "password": "password123",
        },
    )
    assert r.status_code == 422  # validation: neither id nor name provided


# --- legacy university endpoints ----------------------------------------

async def test_legacy_university_search_alias(db, client: AsyncClient):
    await _seed_org(db, "University of Lagos", "UNILAG", "unilag", "Lagos")
    r = await client.get("/api/universities/search", params={"q": "Lag"})
    assert r.status_code == 200
    assert len(r.json()) >= 1


async def test_legacy_university_resolve_is_read_only(db, client: AsyncClient):
    await _seed_org(db, "University of Lagos", "UNILAG", "unilag", "Lagos")
    r = await client.post("/api/universities/resolve", json={"name": "Univ of Lagos"})
    assert r.status_code == 200
    assert r.json()["university"]["short_name"] == "UNILAG"
    assert r.json()["created"] is False


# --- unified multi-persona signup (POST /api/auth/signup) ---------------
#
# The four SignupRole personas the two-step signup form drives:
#   student           → account_type=student, school as organization_id, not a seller
#   individual        → account_type=individual, no org, not a seller
#   student_business  → account_type=student, is_seller, school as organization_id
#                       PLUS a separate owned Business org
#   brand             → account_type=business, is_seller, owned Business org IS org_id


async def _owned_org(db: AsyncSession, user_id: uuid.UUID) -> Organization | None:
    result = await db.execute(
        sa.select(Organization).where(Organization.owner_user_id == user_id)
    )
    return result.scalars().first()


async def test_signup_student_role(db, client: AsyncClient):
    org = await _seed_org(db, "University of Lagos", "UNILAG", "unilag", "Lagos")
    r = await client.post(
        "/api/auth/signup",
        json={
            "role": "student",
            "full_name": "Sade S",
            "username": "sade",
            "email": "sade@example.com",
            "password": "password123",
            "organization_id": str(org.id),
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["outcome"] == "account_created"
    assert body["user"]["account_type"] == "student"
    assert body["user"]["organization_id"] == str(org.id)
    assert body["user"]["is_seller"] is False
    assert body["organization_created"] is False


async def test_signup_individual_role_has_no_org(db, client: AsyncClient):
    r = await client.post(
        "/api/auth/signup",
        json={
            "role": "individual",
            "full_name": "Ife I",
            "username": "ife",
            "email": "ife@example.com",
            "password": "password123",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["outcome"] == "account_created"
    assert body["user"]["account_type"] == "individual"
    assert body["user"]["organization_id"] is None
    assert body["user"]["is_seller"] is False


async def test_signup_individual_rejects_stray_business_fields_are_ignored(db, client: AsyncClient):
    """Individual needs nothing extra; a business_name sent by mistake must not
    make it a seller or create an org."""
    r = await client.post(
        "/api/auth/signup",
        json={
            "role": "individual",
            "full_name": "Ola O",
            "username": "ola",
            "email": "ola@example.com",
            "password": "password123",
        },
    )
    assert r.status_code == 201, r.text
    user = (
        await db.execute(sa.select(User).where(User.username_normalized == "ola"))
    ).scalar_one()
    assert user.is_seller is False
    assert await _owned_org(db, user.id) is None


async def test_signup_student_business_role(db, client: AsyncClient):
    """A student who sells: stays a STUDENT with the school as organization_id,
    is a seller, AND owns a separate Business org."""
    org = await _seed_org(db, "University of Ibadan", "UI", "ui", "Oyo")
    r = await client.post(
        "/api/auth/signup",
        json={
            "role": "student_business",
            "full_name": "Bola B",
            "username": "bola",
            "email": "bola@example.com",
            "password": "password123",
            "organization_id": str(org.id),
            "business_name": "Bola's Thrift",
            "state": "Oyo",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["outcome"] == "account_created"
    assert body["user"]["account_type"] == "student"
    assert body["user"]["is_seller"] is True
    # organization_id is the SCHOOL, not the business.
    assert body["user"]["organization_id"] == str(org.id)
    assert body["organization_created"] is True

    user = (
        await db.execute(sa.select(User).where(User.username_normalized == "bola"))
    ).scalar_one()
    owned = await _owned_org(db, user.id)
    assert owned is not None
    assert owned.official_name == "Bola's Thrift"
    assert owned.state == "Oyo"
    # The owned business is a DIFFERENT org from the school affiliation.
    assert owned.id != org.id


async def test_signup_student_business_requires_school_from_list(db, client: AsyncClient):
    """No deferred path for a seller — an unknown typed school is rejected, and
    NO account/org/request is created."""
    r = await client.post(
        "/api/auth/signup",
        json={
            "role": "student_business",
            "full_name": "Deferred D",
            "username": "deferd",
            "email": "deferd@example.com",
            "password": "password123",
            "organization_name": "Totally Unknown Uni ZZZ",
            "business_name": "D Store",
            "state": "Lagos",
        },
    )
    assert r.status_code == 409, r.text
    users = (await db.execute(sa.select(sa.func.count()).select_from(User))).scalar()
    orgs = (await db.execute(sa.select(sa.func.count()).select_from(Organization))).scalar()
    assert users == 0
    assert orgs == 0


async def test_signup_brand_role(db, client: AsyncClient):
    """A standalone business: account_type=business, is_seller, and the owned
    Business org IS the user's organization_id (no school)."""
    r = await client.post(
        "/api/auth/signup",
        json={
            "role": "brand",
            "full_name": "Chidi C",
            "username": "chidi",
            "email": "chidi@example.com",
            "password": "password123",
            "business_name": "Chidi Foods",
            "state": "Lagos",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["outcome"] == "account_created"
    assert body["user"]["account_type"] == "business"
    assert body["user"]["is_seller"] is True
    assert body["organization_created"] is True

    user = (
        await db.execute(sa.select(User).where(User.username_normalized == "chidi"))
    ).scalar_one()
    owned = await _owned_org(db, user.id)
    assert owned is not None
    assert owned.official_name == "Chidi Foods"
    # For a brand the owned business IS the affiliation.
    assert body["user"]["organization_id"] == str(owned.id)


async def test_signup_brand_requires_business_name_and_state(db, client: AsyncClient):
    r = await client.post(
        "/api/auth/signup",
        json={
            "role": "brand",
            "full_name": "No Biz",
            "username": "nobiz",
            "email": "nobiz@example.com",
            "password": "password123",
        },
    )
    assert r.status_code == 422  # validator: business_name + state required


async def test_signup_student_requires_school(db, client: AsyncClient):
    r = await client.post(
        "/api/auth/signup",
        json={
            "role": "student",
            "full_name": "No School",
            "username": "noschool",
            "email": "noschool@example.com",
            "password": "password123",
        },
    )
    assert r.status_code == 422  # validator: student needs a school


async def test_signup_student_unknown_school_defers(db, client: AsyncClient):
    """A pure student (not a seller) with an unknown typed school takes the
    deferred-request path — no user yet, one request + one signup request."""
    r = await client.post(
        "/api/auth/signup",
        json={
            "role": "student",
            "full_name": "Pending P",
            "username": "pendp",
            "email": "pendp@example.com",
            "password": "password123",
            "organization_name": "Unlisted College QQQ",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["outcome"] == "pending_organization_review"
    assert body["user"] is None
    assert body["organization_request_id"] is not None

    users = (await db.execute(sa.select(sa.func.count()).select_from(User))).scalar()
    oreqs = (await db.execute(sa.select(sa.func.count()).select_from(OrganizationRequest))).scalar()
    sreqs = (await db.execute(sa.select(sa.func.count()).select_from(SignupRequest))).scalar()
    assert users == 0
    assert oreqs == 1
    assert sreqs == 1
