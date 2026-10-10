"""
Account-capability service — post-signup transitions on an existing account.

Three flows live here, all distinct from signup (the account already exists;
the user is authenticated):

  - upgrade_to_business():  the "Start selling" CTA. A non-selling account
    (student or individual) gains the selling capability by creating a
    Business-group organization it owns. Crucially it KEEPS its account_type —
    a student who starts a business is still a student (identity), now also a
    seller (capability). See the identity-vs-capability split in
    app/models/user.py.

  - set_graduation():  a student self-marks (or un-marks) graduated. Purely
    informational — no badge, no login gating. Its one behavioural effect: a
    graduated user who OWNS a business is prompted to update that business's
    pickup address, because a campus pickup point likely no longer applies.
    The prompt is signalled back to the caller (needs_pickup_update); this
    service does not touch the address itself.

  - update_business_profile():  the Business Hub's own writes — business name,
    state, and the pickup address that graduation prompts for. Together with
    get_owned_business() these are the only Hub operations backed by real
    columns today; everything else doc 16 describes (revenue, escrow, orders,
    inventory, analytics, payouts) has no table yet.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.models.organization import Organization
from app.models.user import User
from app.repositories.organization import OrganizationRepository
from app.repositories.user import UserRepository
from app.services import organization as org_service


@dataclass
class UpgradeResult:
    user: User
    organization: Organization


@dataclass
class GraduationResult:
    user: User
    graduated: bool
    # True when the user owns a business, so the UI should prompt them to
    # review the pickup address. Always False when un-graduating.
    needs_pickup_update: bool = False


async def upgrade_to_business(
    db: AsyncSession,
    user: User,
    *,
    business_name: str,
    state: str | None,
) -> UpgradeResult:
    """Turn an existing account into a seller by creating a Business org it
    owns. Idempotency guard: a user who already owns a business can't create a
    second one here (they'd manage it in the Business Hub instead)."""
    org_repo = OrganizationRepository(db)

    existing = await org_repo.get_owned_by_user(user.id)
    if existing is not None:
        raise ConflictError(
            "You already have a business on CartFlow.",
            fields={"business_name": "You already own a business."},
        )

    type_id = await org_service.default_business_type_id(db)
    org = await org_repo.create_business(
        official_name=business_name,
        owner_user_id=user.id,
        type_id=type_id,
        state=state,
    )

    # Capability flip. account_type is deliberately UNCHANGED — a student who
    # starts selling stays a student.
    user.is_seller = True
    # First business also becomes the account's affiliation if it had none
    # (an individual with organization_id=NULL); never overwrite a student's
    # school.
    if user.organization_id is None:
        user.organization_id = org.id
    await db.flush()

    return UpgradeResult(user=user, organization=org)


async def set_graduation(
    db: AsyncSession, user: User, *, graduated: bool
) -> GraduationResult:
    """Set or clear the graduation timestamp. Returns needs_pickup_update=True
    only when marking graduated AND the user owns a business."""
    user.graduated_at = datetime.now(timezone.utc) if graduated else None
    await db.flush()

    needs_pickup_update = False
    if graduated:
        owned = await OrganizationRepository(db).get_owned_by_user(user.id)
        needs_pickup_update = owned is not None

    return GraduationResult(
        user=user, graduated=graduated, needs_pickup_update=needs_pickup_update
    )


async def update_profile(
    db: AsyncSession, user: User, *, changes: dict
) -> User:
    """Apply an edit to the caller's own identity fields.

    `changes` is a `ProfileUpdateRequest.model_dump(exclude_unset=True)` — the
    keys the client actually sent, which is what makes "clear my bio" (`""`)
    distinguishable from "leave my bio alone" (absent).

    The three names are applied verbatim except the handle, which is the only one
    with a rule attached: it must be unique, so it's checked against
    `username_normalized` before either column moves. A no-op change (same handle,
    different casing you already own) is allowed through — `@AdaLovelace` fixing
    their own capitalisation is not a collision with themselves, and the profile
    route canonicalises casing anyway.

    Raises ConflictError with a per-field message, the same shape signup uses, so
    the settings form can highlight the username input rather than showing a
    banner.
    """
    if "username" in changes:
        new_username = changes["username"]
        normalized = new_username.lower()
        if normalized != user.username_normalized:
            existing = await UserRepository(db).get_by_username_normalized(normalized)
            if existing is not None:
                raise ConflictError(
                    "This username is already taken.",
                    fields={"username": "This username is already taken."},
                )
        # Both columns move together, always: `username` keeps the casing as
        # typed and `username_normalized` is the lookup key. Letting them drift
        # would make the account unreachable at its own URL.
        user.username = new_username
        user.username_normalized = normalized

    if "display_name" in changes:
        user.display_name = changes["display_name"]
    if "full_name" in changes:
        user.full_name = changes["full_name"]
    if "bio" in changes:
        user.bio = changes["bio"]

    await db.flush()
    return user


async def get_owned_business(db: AsyncSession, user: User) -> Organization:
    """The business this user owns, or NotFoundError.

    Every Business Hub read and write goes through here, so the ownership check
    is written once. It resolves through `owner_user_id` — the source of truth —
    rather than trusting `users.is_seller`, which is only a denormalized mirror:
    if the two ever drift, the Hub must follow the row that actually exists, not
    the flag.
    """
    owned = await OrganizationRepository(db).get_owned_by_user(user.id)
    if owned is None:
        raise NotFoundError("You don't have a business on CartFlow yet.")
    return owned


async def update_business_profile(
    db: AsyncSession,
    user: User,
    *,
    changes: dict,
) -> Organization:
    """Apply a partial edit to the business this user owns.

    `changes` is a `model_dump(exclude_unset=True)` of BusinessProfileUpdateRequest,
    so only the keys the client actually sent are touched — passing an explicit
    `pickup_address: None` clears the address, while omitting the key leaves it.

    This closes a real dead-end: `pickup_address` could be set at signup and
    `set_graduation` tells a graduated seller to update it, but until now nothing
    could write it.

    `slug` is left alone on rename (see BusinessProfileUpdateRequest) and
    `status` is never editable here — verification is an admin decision, so a
    seller must not be able to promote their own shop out of 'unverified'.
    """
    org = await get_owned_business(db, user)

    if "business_name" in changes:
        org.official_name = changes["business_name"]
    if "state" in changes:
        org.state = changes["state"]
    if "pickup_address" in changes:
        org.pickup_address = changes["pickup_address"]

    await db.flush()
    return org
