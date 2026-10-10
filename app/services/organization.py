"""
Organization service — business logic for the organization foundation.

Owns the V1 signup/directory/request workflows (spec items #2-#7).
"""

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationAppError
from app.core.security import hash_password
from app.models.organization import Organization, OrganizationType
from app.models.organization_request import OrganizationRequest, SignupRequest
from app.models.user import AccountStatus, AccountType, User
from app.repositories.organization import (
    OrganizationRepository,
    OrganizationRequestRepository,
    SignupRequestRepository,
    TaxonomyRepository,
)
from app.repositories.user import UserRepository
from app.services.email_verification import send_verification_email

logger = logging.getLogger("cartflow.organization")

# Taxonomy slugs used by the signup/upgrade flows. Students are matched against
# the whole Education GROUP (universities, polytechnics, colleges, …) rather
# than a single type — the plan opened signup to all Education orgs. Businesses
# default to the SME type within the Business group (no type picker at signup;
# editable later in the Business Hub).
EDUCATION_GROUP_SLUG = "education"
BUSINESS_GROUP_SLUG = "business"
DEFAULT_BUSINESS_TYPE_SLUG = "sme"


async def _resolve_group_id(db: AsyncSession, group_slug: str) -> uuid.UUID | None:
    """Look up a group id by slug, tolerating a missing row (returns None so
    the caller falls back to an unscoped query rather than crashing)."""
    group = await TaxonomyRepository(db).get_group_by_slug(group_slug)
    return group.id if group else None


async def resolve_education_organization(
    db: AsyncSession, name: str
) -> tuple[Organization | None, bool]:
    """Student signup resolution, scoped to the ENTIRE Education group (not just
    universities). Returns (organization, found)."""
    org_repo = OrganizationRepository(db)
    group_id = await _resolve_group_id(db, EDUCATION_GROUP_SLUG)
    match = await org_repo.find_match(name, group_id=group_id)
    if match:
        return match, True
    return None, False


async def default_business_type_id(db: AsyncSession) -> uuid.UUID | None:
    """The Business-group 'SME' type id — the default for new businesses.
    Nullable-tolerant: a business org with a NULL type is still valid, and the
    type is user-editable in the Business Hub afterwards."""
    org_type = await TaxonomyRepository(db).get_type_by_slug(DEFAULT_BUSINESS_TYPE_SLUG)
    return org_type.id if org_type else None



async def search_autocomplete(
    db: AsyncSession,
    query: str,
    *,
    type_slug: str | None = "university",
    limit: int = 5,
) -> list[Organization]:
    """Typeahead search for signup (spec item #3). Returns top-N; no
    '53 matches found' indicator. `type_slug` defaults to "university"
    (V1 frontend only exposes universities)."""
    taxonomy_repo = TaxonomyRepository(db)
    org_repo = OrganizationRepository(db)

    type_id = None
    if type_slug:
        org_type = await taxonomy_repo.get_type_by_slug(type_slug)
        if org_type:
            type_id = org_type.id

    return await org_repo.search(query, type_id=type_id, limit=limit)


async def list_directory(
    db: AsyncSession,
    *,
    country: str | None = None,
    state: str | None = None,
    type_slug: str | None = None,
    page: int = 1,
    per_page: int = 20,
) -> tuple[list[Organization], int, int]:
    """Paginated directory (spec item #4). Returns (orgs, total, pages)."""
    taxonomy_repo = TaxonomyRepository(db)
    org_repo = OrganizationRepository(db)

    type_id = None
    if type_slug:
        org_type = await taxonomy_repo.get_type_by_slug(type_slug)
        if org_type:
            type_id = org_type.id

    offset = (page - 1) * per_page
    orgs, total = await org_repo.list_directory(
        country=country,
        state=state,
        type_id=type_id,
        limit=per_page,
        offset=offset,
    )

    pages = (total + per_page - 1) // per_page if per_page > 0 else 0
    return orgs, total, pages


async def resolve_organization(
    db: AsyncSession,
    name: str,
    *,
    type_slug: str | None = "university",
) -> tuple[Organization, bool]:
    """Read-only resolution for the signup happy-path (item #6). Returns
    (organization, found). `found=False` means no match — the caller should
    offer 'browse directory / request new' rather than auto-creating."""
    taxonomy_repo = TaxonomyRepository(db)
    org_repo = OrganizationRepository(db)

    type_id = None
    if type_slug:
        org_type = await taxonomy_repo.get_type_by_slug(type_slug)
        if org_type:
            type_id = org_type.id

    match = await org_repo.find_match(name, type_id=type_id)
    if match:
        return match, True

    return None, False  # type: ignore — caller checks the bool


async def create_organization_request(
    db: AsyncSession,
    requested_name: str,
    country: str = "Nigeria",
    state: str | None = None,
    type_slug: str | None = None,
) -> OrganizationRequest:
    """File a request for a missing organization (spec item #6). Returns the
    pending request; the admin approval flow is out-of-scope for V1."""
    taxonomy_repo = TaxonomyRepository(db)
    request_repo = OrganizationRequestRepository(db)

    type_id = None
    if type_slug:
        org_type = await taxonomy_repo.get_type_by_slug(type_slug)
        if org_type:
            type_id = org_type.id

    return await request_repo.create(
        requested_name=requested_name,
        country=country,
        state=state,
        organization_type_id=type_id,
        status="pending",
    )


async def create_signup_request(
    db: AsyncSession,
    organization_request_id: uuid.UUID,
    full_name: str,
    email: str,
    username: str,
    password: str,
) -> SignupRequest:
    """Deferred signup tied to a pending organization request (spec item #7).
    The password is hashed immediately — we never store raw passwords, even
    in a deferred-signup row. Returns the pending signup; account creation
    happens later when the org request is approved."""
    user_repo = UserRepository(db)
    signup_repo = SignupRequestRepository(db)

    email_normalized = email.lower()
    username_normalized = username.lower()

    # Check existing users
    if await user_repo.email_exists(email_normalized):
        raise ConflictError(
            "An account with this email already exists.",
            fields={"email": "This email is already registered."},
        )
    if await user_repo.username_exists(username_normalized):
        raise ConflictError(
            "This username is already taken.",
            fields={"username": "This username is already taken."},
        )

    # Check pending requests (another user may be waiting on the same org)
    existing_email = await signup_repo.find_pending_by_email(email_normalized)
    if existing_email:
        raise ConflictError(
            "This email is already in a pending signup request.",
            fields={"email": "A signup request with this email is under review."},
        )

    existing_username = await signup_repo.find_pending_by_username(username_normalized)
    if existing_username:
        raise ConflictError(
            "This username is already in a pending signup request.",
            fields={"username": "A signup request with this username is under review."},
        )

    return await signup_repo.create(
        full_name=full_name,
        email=email_normalized,
        username=username,
        username_normalized=username_normalized,
        password_hash=hash_password(password),
        organization_request_id=organization_request_id,
        status="pending",
    )


async def approve_organization_request(
    db: AsyncSession,
    request_id: uuid.UUID,
    *,
    reviewed_by: uuid.UUID,
) -> tuple[Organization, list[User]]:
    """Admin approval: create/link org → complete pending signups (spec
    item #6 final step). Returns (organization, list_of_new_users). Each
    user is created in PENDING_VERIFICATION and gets a verification email
    (best-effort — log and continue if email sending fails; the resend
    endpoint exists for recovery)."""
    request_repo = OrganizationRequestRepository(db)
    signup_repo = SignupRequestRepository(db)
    org_repo = OrganizationRepository(db)
    user_repo = UserRepository(db)

    org_request = await request_repo.get(request_id)
    if org_request is None:
        raise NotFoundError("Organization request not found.")

    if org_request.status != "pending":
        raise ValidationAppError(
            f"Request is already {org_request.status}.",
            fields={"_": "This request has already been processed."},
        )

    # Create or match the organization (fuzzy, to avoid duplicates)
    org, created = await org_repo.get_or_create(
        org_request.requested_name,
        type_id=org_request.organization_type_id,
    )

    # Mark the org request approved
    await request_repo.update(
        org_request,
        status="approved",
        resulting_organization_id=org.id,
        reviewed_by=reviewed_by,
    )

    # Complete all pending signups for this request
    pending = await signup_repo.list_pending_for_request(request_id)
    new_users: list[User] = []

    for signup in pending:
        # Re-check uniqueness (another admin approval may have beaten us)
        email_exists = await user_repo.email_exists(signup.email)
        username_exists = await user_repo.username_exists(signup.username_normalized)

        if email_exists or username_exists:
            logger.warning(
                "Signup %s email/username now taken; skipping account creation.",
                signup.id,
            )
            continue

        new_user = await user_repo.create(
            account_type=AccountType.STUDENT,
            account_status=AccountStatus.PENDING_VERIFICATION,
            email=signup.email,
            password_hash=signup.password_hash,
            username=signup.username,
            username_normalized=signup.username_normalized,
            display_name=signup.full_name,
            full_name=signup.full_name,
            organization_id=org.id,
        )

        await signup_repo.update(
            signup,
            status="completed",
            resulting_user_id=new_user.id,
        )

        # Best-effort verification email
        try:
            await send_verification_email(db, new_user)
        except Exception:
            logger.exception(
                "Failed to send verification email for user %s; account created.",
                new_user.id,
            )

        new_users.append(new_user)

    return org, new_users
