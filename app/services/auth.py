"""
Auth/signup service.

Per PRD Chapter 12's layering ("Service layer: contains business rules,
enforces state transitions, coordinates repositories... Repository layer:
..."), this module owns the actual signup workflow. The router should
only parse the request, call this, and return the response — it should
not contain uniqueness checks, password hashing, or organization
resolution itself.

Chapter 3 sec 4 (Student Sign-Up Flow, Step 1) requirements enforced here:
  - full name, username, email, password, organization all required.
  - organization is resolved to a record, never stored as free text.
  - account starts in PENDING_VERIFICATION (Chapter 3 sec 9 / sec 10) —
    email verification is a separate, later step, not handled here.

V1 pivot (spec items #5/#6): the not-found path no longer silently creates
an organization at signup. Instead:
  - Organization found → create the account now (as before).
  - Organization NOT found → file an OrganizationRequest + a deferred
    SignupRequest (password already hashed) and DO NOT create the account.
    An admin approves the org later, which completes the signup (no
    re-registration). See app/services/organization.py.

Multi-persona (Milestone 1): `signup()` dispatches on `role`:
  - student           → Education-group resolution + the deferred-request
    fallback below. account_type=STUDENT, not a seller.
  - individual        → personal account, no organization. account_type=INDIVIDUAL.
  - student_business  → account_type=STUDENT + is_seller=True. Keeps the school
    as organization_id AND owns a separate Business-group org (default type SME).
    This is the persona graduation + pickup-address logic targets.
  - brand             → account_type=BUSINESS + is_seller=True + a Business-group
    org the user owns (default type SME). Standalone; no school. No deferred path
    — a business names its own org, it isn't resolved against a curated list.
`signup_student()` stays as a thin role="student" wrapper for the legacy
/api/auth/signup/student endpoint.

Passwordless (Google) accounts: `password` may be None on the payload. Such an
account is created with password_hash=NULL and email pre-verified (the caller
sets email_verified_at) — identity is proven by Google, never a local password.

Chapter 3 sec 9 (Email Verification): after an account is created we attempt
to send the verification email immediately, best-effort — a Resend outage
should delay verification, not prevent account creation (the
/api/auth/resend-verification endpoint recovers from this). If sending fails
we log it and still return the created user; get_db commits normally.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError
from app.core.security import hash_password
from app.models.user import AccountStatus, AccountType, User
from app.models.organization import Organization
from app.repositories.organization import OrganizationRepository
from app.repositories.user import UserRepository
from app.schemas.user import SignUpRequest, StudentSignUpRequest
from app.services import organization as org_service
from app.services.email_verification import send_verification_email

logger = logging.getLogger("cartflow.auth")

# The type a student's DEFERRED request is filed under when their org isn't
# found. Students now match the whole Education group, but an unknown name is
# overwhelmingly a university, and the admin can re-type it on approval.
_STUDENT_REQUEST_TYPE_SLUG = "university"


@dataclass
class SignupResult:
    """Outcome of signup(). Exactly one of the two branches applies:
      - outcome="account_created": `user` is set.
      - outcome="pending_organization_review": `organization_request_id` is
        set, `user` is None (deferred until admin approval). Only the student
        role can produce this branch."""

    outcome: str
    user: User | None = None
    organization_created: bool = False
    organization_request_id: uuid.UUID | None = None


async def _assert_unique(user_repo: UserRepository, email_normalized: str, username_normalized: str) -> None:
    """Reject a duplicate email/username before any row (account OR deferred
    request) is created."""
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


def _password_hash_or_none(password: str | None) -> str | None:
    """Hash a local password, or None for a passwordless (Google) account.
    Never stores a raw password."""
    return hash_password(password) if password else None


async def _finalize_new_user(db: AsyncSession, user: User, *, send_verification: bool) -> None:
    """Best-effort verification email for a freshly-created user. Skipped for
    accounts already verified out-of-band (Google), whose email is trusted."""
    if not send_verification:
        return
    try:
        await send_verification_email(db, user)
    except Exception:
        logger.exception(
            "Failed to send verification email for new user %s; account created anyway.",
            user.id,
        )


async def signup(
    db: AsyncSession, payload: SignUpRequest, *, google_sub: str | None = None
) -> SignupResult:
    """Unified multi-persona signup. Dispatches on `payload.role`.

    `google_sub` is set (and `payload.password` is None) for the Google
    finish-signup path — the router has already verified the token and unpacked
    the identity. It's stamped on the new user so a returning Google login
    matches on it."""
    if payload.role == "student":
        return await _signup_student(db, payload, google_sub=google_sub)
    if payload.role == "individual":
        return await _signup_individual(db, payload, google_sub=google_sub)
    if payload.role == "student_business":
        return await _signup_student_business(db, payload, google_sub=google_sub)
    if payload.role == "brand":
        return await _signup_brand(db, payload, google_sub=google_sub)
    # Unreachable: SignupRole is a closed Literal validated by pydantic.
    raise ConflictError(f"Unsupported signup role: {payload.role!r}")


async def _resolve_school_or_none(
    db: AsyncSession, payload: SignUpRequest
) -> tuple[Organization | None, bool]:
    """Resolve a student's school from either a picked organization_id or a
    typed organization_name, scoped to the whole Education group. Returns
    (org, resolved) where resolved=False means a typed name matched nothing —
    the caller decides whether to defer (pure student) or reject (Google /
    student-business, which can't take the deferred path)."""
    org_repo = OrganizationRepository(db)

    if payload.organization_id is not None:
        # Frontend already picked one from /api/organizations/search.
        org = await org_repo.get(payload.organization_id)
        if org is None:
            raise ConflictError(
                "The selected school could not be found.",
                fields={"organization_id": "Please pick a school from the list."},
            )
        return org, True

    matched, found = await org_service.resolve_education_organization(
        db, payload.organization_name
    )
    return (matched, True) if found else (None, False)


async def _signup_student(
    db: AsyncSession, payload: SignUpRequest, *, google_sub: str | None = None
) -> SignupResult:
    user_repo = UserRepository(db)

    email_normalized = payload.email.lower()
    username_normalized = payload.username.lower()
    await _assert_unique(user_repo, email_normalized, username_normalized)

    # --- Resolve the school (whole Education group) ---------------------- #
    org, resolved = await _resolve_school_or_none(db, payload)

    # --- Not found → deferred request, no account yet (spec item #6) ------ #
    # Only reachable when a raw name (not a picked id) failed to resolve, and
    # only pure students take this path — passwordless (Google) students can't,
    # since a deferred SignupRequest stores a password_hash (NOT NULL). The
    # finish-signup UI forces Google students to pick a school from the list.
    if not resolved:
        if payload.password is None:
            raise ConflictError(
                "Please choose your school from the list.",
                fields={"organization_name": "Pick your school from the suggestions."},
            )
        org_request = await org_service.create_organization_request(
            db,
            requested_name=payload.organization_name,
            type_slug=_STUDENT_REQUEST_TYPE_SLUG,
        )
        await org_service.create_signup_request(
            db,
            organization_request_id=org_request.id,
            full_name=payload.full_name,
            email=payload.email,
            username=payload.username,
            password=payload.password,
        )
        return SignupResult(
            outcome="pending_organization_review",
            organization_request_id=org_request.id,
        )

    # --- Found → create the account now ---------------------------------- #
    new_user = await user_repo.create(
        account_type=AccountType.STUDENT,
        account_status=AccountStatus.PENDING_VERIFICATION,
        email=email_normalized,
        password_hash=_password_hash_or_none(payload.password),
        google_sub=google_sub,
        username=payload.username,
        username_normalized=username_normalized,
        display_name=payload.full_name,
        full_name=payload.full_name,
        organization_id=org.id,
        email_verified_at=_google_verified_at(payload),
    )
    await _finalize_new_user(db, new_user, send_verification=payload.password is not None)
    return SignupResult(outcome="account_created", user=new_user)


async def _signup_individual(
    db: AsyncSession, payload: SignUpRequest, *, google_sub: str | None = None
) -> SignupResult:
    user_repo = UserRepository(db)

    email_normalized = payload.email.lower()
    username_normalized = payload.username.lower()
    await _assert_unique(user_repo, email_normalized, username_normalized)

    new_user = await user_repo.create(
        account_type=AccountType.INDIVIDUAL,
        account_status=AccountStatus.PENDING_VERIFICATION,
        email=email_normalized,
        password_hash=_password_hash_or_none(payload.password),
        google_sub=google_sub,
        username=payload.username,
        username_normalized=username_normalized,
        display_name=payload.full_name,
        full_name=payload.full_name,
        organization_id=None,
        email_verified_at=_google_verified_at(payload),
    )
    await _finalize_new_user(db, new_user, send_verification=payload.password is not None)
    return SignupResult(outcome="account_created", user=new_user)


async def _signup_student_business(
    db: AsyncSession, payload: SignUpRequest, *, google_sub: str | None = None
) -> SignupResult:
    """A student who also sells. account_type stays STUDENT (identity), but
    is_seller=True and they own a Business org (capability). organization_id
    points at their SCHOOL — the university affiliation is what makes graduation
    + pickup-address logic apply to this persona.

    No deferred-request fallback: a seller needs a real account immediately, so
    the school must resolve here (the UI forces a pick from the list)."""
    user_repo = UserRepository(db)
    org_repo = OrganizationRepository(db)

    email_normalized = payload.email.lower()
    username_normalized = payload.username.lower()
    await _assert_unique(user_repo, email_normalized, username_normalized)

    org, resolved = await _resolve_school_or_none(db, payload)
    if not resolved:
        raise ConflictError(
            "Please choose your school from the list.",
            fields={"organization_name": "Pick your school from the suggestions."},
        )

    new_user = await user_repo.create(
        account_type=AccountType.STUDENT,
        account_status=AccountStatus.PENDING_VERIFICATION,
        email=email_normalized,
        password_hash=_password_hash_or_none(payload.password),
        google_sub=google_sub,
        username=payload.username,
        username_normalized=username_normalized,
        display_name=payload.full_name,
        full_name=payload.full_name,
        # organization_id is the SCHOOL, not the business — the business is a
        # separate owned org (below). This keeps the campus affiliation.
        organization_id=org.id,
        is_seller=True,
        email_verified_at=_google_verified_at(payload),
    )

    type_id = await org_service.default_business_type_id(db)
    await org_repo.create_business(
        official_name=payload.business_name,
        owner_user_id=new_user.id,
        type_id=type_id,
        state=payload.state,
    )
    await db.flush()

    await _finalize_new_user(db, new_user, send_verification=payload.password is not None)
    return SignupResult(outcome="account_created", user=new_user, organization_created=True)


async def _signup_brand(
    db: AsyncSession, payload: SignUpRequest, *, google_sub: str | None = None
) -> SignupResult:
    """A standalone business ('Brand'). account_type=BUSINESS, is_seller=True,
    and organization_id IS the business they own — no school affiliation."""
    user_repo = UserRepository(db)
    org_repo = OrganizationRepository(db)

    email_normalized = payload.email.lower()
    username_normalized = payload.username.lower()
    await _assert_unique(user_repo, email_normalized, username_normalized)

    # Create the user first (account_type=BUSINESS, is_seller=True), then the
    # org they own — org.owner_user_id needs the user id, and is_seller is the
    # denormalized mirror of "owns a Business org".
    new_user = await user_repo.create(
        account_type=AccountType.BUSINESS,
        account_status=AccountStatus.PENDING_VERIFICATION,
        email=email_normalized,
        password_hash=_password_hash_or_none(payload.password),
        google_sub=google_sub,
        username=payload.username,
        username_normalized=username_normalized,
        display_name=payload.full_name,
        full_name=payload.full_name,
        organization_id=None,
        is_seller=True,
        email_verified_at=_google_verified_at(payload),
    )

    type_id = await org_service.default_business_type_id(db)
    org = await org_repo.create_business(
        official_name=payload.business_name,
        owner_user_id=new_user.id,
        type_id=type_id,
        state=payload.state,
    )
    # The business's own org is also the user's affiliation.
    new_user.organization_id = org.id
    await db.flush()

    await _finalize_new_user(db, new_user, send_verification=payload.password is not None)
    return SignupResult(outcome="account_created", user=new_user, organization_created=True)


def _google_verified_at(payload: SignUpRequest) -> datetime | None:
    """Google-path accounts (no local password) have a Google-verified email,
    so they're created pre-verified. Local-password accounts verify by email."""
    return datetime.now(timezone.utc) if payload.password is None else None


async def signup_student(db: AsyncSession, payload: StudentSignUpRequest) -> SignupResult:
    """Back-compat wrapper for the legacy /api/auth/signup/student endpoint.
    Adapts the student-only payload onto the unified flow."""
    unified = SignUpRequest(
        role="student",
        full_name=payload.full_name,
        username=payload.username,
        email=payload.email,
        password=payload.password,
        organization_id=payload.organization_id,
        organization_name=payload.organization_name,
    )
    return await signup(db, unified)


async def find_user_for_google(db: AsyncSession, *, sub: str, email: str) -> User | None:
    """Resolve a returning Google user at callback time. Matches on google_sub
    FIRST (stable across email changes), then falls back to email — and when it
    matches by email, links the google_sub so the next login is a sub match and
    the local-password account gains Google sign-in. Returns None for a brand-
    new user (the caller routes them to finish-signup).

    A NULL-hash email match is a passwordless account created via Google whose
    sub somehow differs — still the same person, so linking is safe. A match on
    a password account means the user is adding Google to an existing login."""
    user_repo = UserRepository(db)

    user = await user_repo.get_by_google_sub(sub)
    if user is not None:
        return user

    user = await user_repo.get_by_email(email.lower())
    if user is not None:
        if user.google_sub is None:
            user.google_sub = sub
            await db.flush()
        return user

    return None

