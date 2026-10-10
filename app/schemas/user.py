"""User-related request/response schemas."""

import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.core.reserved_usernames import RESERVED_USERNAMES
from app.services import avatar as avatar_service

USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9._-]{3,30}$")

# The personas the signup form offers. Kept in one place so the schema and the
# service dispatch agree. Note these are SIGNUP roles, not stored account_types:
#   student           → account_type=student, university, not a seller
#   individual        → account_type=individual, no org
#   student_business  → account_type=student, is_seller, KEEPS university AND
#                       owns a business org (graduation/pickup logic applies)
#   brand             → account_type=business, is_seller, standalone business
SignupRole = Literal["student", "individual", "student_business", "brand"]


def validate_username_value(v: str) -> str:
    """The single source of truth for username rules.

    Extracted from the signup validator so /api/auth/check-username applies
    byte-for-byte the same rules. Two copies would eventually disagree, and
    the failure mode is the worst kind: the live checker says "available",
    then submit rejects it.

    Note the pattern is deliberately permissive about *composition* — a name
    of pure letters like "adalovelace" is valid, and always has been. Digits
    and . _ - are allowed but never required.
    """
    if not USERNAME_PATTERN.match(v):
        raise ValueError(
            "Username can only contain letters, numbers, underscores, "
            "periods, and hyphens (3-30 characters)."
        )
    if v[0] in "._-" or v[-1] in "._-":
        raise ValueError("Username can't start or end with a period, underscore, or hyphen.")
    if re.search(r"[._-]{2,}", v):
        raise ValueError("Username can't contain consecutive periods, underscores, or hyphens.")
    if v.lower() in RESERVED_USERNAMES:
        raise ValueError("This username is reserved and cannot be used")
    return v


class StudentSignUpRequest(BaseModel):
    """PRD Chapter 3 sec 4, Step 1 — Basic identity for Student accounts.

    Organization is accepted as EITHER a resolved `organization_id` (preferred
    — the frontend already picked one from /api/organizations/search) OR a raw
    `organization_name` (fallback). `university_id` / `university_name` are
    accepted as backward-compatible aliases that map onto the organization
    fields (V1 frontend compatibility). At least one must be provided.

    Not-found handling is the service's job: an `organization_name` that
    resolves to nothing becomes an OrganizationRequest + deferred SignupRequest
    (spec item #6), not a silently-created org.
    """

    full_name: str = Field(min_length=1, max_length=150)
    username: str = Field(min_length=3, max_length=30)

    email: EmailStr
    password: str = Field(min_length=8, max_length=255)

    organization_id: uuid.UUID | None = None
    organization_name: str | None = Field(default=None, min_length=2, max_length=255)

    # Deprecated aliases — kept so the existing frontend contract doesn't break.
    university_id: uuid.UUID | None = None
    university_name: str | None = Field(default=None, min_length=2, max_length=255)

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        return validate_username_value(v)

    @model_validator(mode="after")
    def normalize_organization_choice(self):
        # Fold the deprecated university_* aliases onto the organization_*
        # fields, then require at least one. A plain field_validator on a
        # single field wouldn't fire when that field falls back to its default
        # (Pydantic v2 skips defaulted fields), and "nothing provided at all"
        # is exactly the case we must catch — so validate at the model level.
        if self.organization_id is None and self.university_id is not None:
            self.organization_id = self.university_id
        if self.organization_name is None and self.university_name is not None:
            self.organization_name = self.university_name

        if self.organization_id is None and self.organization_name is None:
            raise ValueError(
                "Either organization_id or organization_name is required"
            )
        return self


class SignUpRequest(BaseModel):
    """Unified signup for all four personas.

    Supersedes StudentSignUpRequest (kept for the legacy /signup/student
    endpoint). `role` selects the persona and drives which other fields are
    required:

      - student           → an organization is required (organization_id OR
                            organization_name), resolved against the Education
                            group. Not a seller.
      - individual        → no organization; personal account, stories-only.
      - student_business  → BOTH an Education org (the student's school) AND
                            business_name + state required. account_type stays
                            student; the user also owns a business and can sell.
      - brand             → business_name + state required; a standalone
                            business (account_type=business), no school.

    `password` is OPTIONAL: the Google finish-signup step sends a signed
    `google_token` instead, and the account is created passwordless. Exactly
    one of (password, google_token) must be present — enforced here so neither
    a passwordless-without-Google nor a both-supplied request slips through.
    """

    role: SignupRole
    full_name: str = Field(min_length=1, max_length=150)
    username: str = Field(min_length=3, max_length=30)
    email: EmailStr

    # Local-password path. Optional because the Google path is passwordless.
    password: str | None = Field(default=None, min_length=8, max_length=255)
    # Google finish-signup path: the short-lived signed token minted by the
    # OAuth callback (carries the verified sub/email/name). Opaque to the schema
    # — the service verifies and unpacks it.
    google_token: str | None = None

    # School selection — required for student and student_business (same contract
    # as StudentSignUpRequest).
    organization_id: uuid.UUID | None = None
    organization_name: str | None = Field(default=None, min_length=2, max_length=255)

    # Business fields — required for student_business and brand. No type picker:
    # the service defaults new orgs to SME, editable later in the Business Hub.
    # State is one of NG_STATES (frontend dropdown); not enum-validated here so
    # the list stays single-sourced in JS.
    business_name: str | None = Field(default=None, min_length=2, max_length=255)
    state: str | None = Field(default=None, min_length=2, max_length=100)

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        return validate_username_value(v)

    @model_validator(mode="after")
    def validate_credentials_and_role_fields(self):
        # Exactly one credential path. Model-level because "neither supplied"
        # can't be caught by a per-field validator (defaults are skipped).
        has_password = self.password is not None
        has_google = self.google_token is not None
        if has_password and has_google:
            raise ValueError("Provide either a password or a Google sign-in, not both")
        if not has_password and not has_google:
            raise ValueError("A password is required")

        # Role-conditional required fields.
        needs_school = self.role in ("student", "student_business")
        needs_business = self.role in ("student_business", "brand")

        if needs_school and self.organization_id is None and self.organization_name is None:
            raise ValueError("Students must choose a school")
        if needs_business:
            if not self.business_name:
                raise ValueError("A business name is required")
            if not self.state:
                raise ValueError("A state is required")
        # individual: nothing extra required.

        return self


class SignUpResponse(BaseModel):
    """Response for the unified /api/auth/signup endpoint.

    Same two outcomes as the student flow — `account_created` (user populated)
    or `pending_organization_review` (a student's org wasn't found, so a
    request + deferred signup were filed and `user` is null until approval)."""

    outcome: str
    message: str
    user: "UserOut | None" = None
    organization_created: bool = False
    organization_request_id: uuid.UUID | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    public_id: uuid.UUID
    account_type: str
    account_status: str
    email: str
    username: str
    display_name: str
    # The private one of the three names. Safe here — UserOut is only ever
    # returned to the account's OWN session (see PublicUserOut for everyone
    # else, which carries neither this nor `email`).
    full_name: str | None = None
    bio: str | None = None
    organization_id: uuid.UUID | None = None
    is_seller: bool = False
    graduated_at: datetime | None = None
    email_verified_at: datetime | None = None
    created_at: datetime


class StudentSignUpResponse(BaseModel):
    """Two possible outcomes (spec items #5/#6):
      - `account_created`: the organization existed; `user` is populated.
      - `pending_organization_review`: the typed organization didn't exist, so
        a request + deferred signup were filed. `user` is null until an admin
        approves the request (no re-registration needed)."""

    outcome: str
    message: str
    user: UserOut | None = None
    organization_created: bool = Field(
        default=False,
        description="True if a new (unverified) organization row was created.",
    )
    organization_request_id: uuid.UUID | None = Field(
        default=None,
        description="Set when outcome is pending_organization_review.",
    )


class BusinessUpgradeRequest(BaseModel):
    """The "Start selling" CTA — an existing account creates a business it owns.
    No type picker (defaults to SME, editable later in the Business Hub); state
    is one of NG_STATES from the frontend dropdown."""

    business_name: str = Field(min_length=2, max_length=255)
    state: str | None = Field(default=None, min_length=2, max_length=100)


class BusinessUpgradeResponse(BaseModel):
    message: str
    user: UserOut
    organization_id: uuid.UUID


class GraduationRequest(BaseModel):
    """Self-toggle for graduation. `graduated=false` un-marks it."""

    graduated: bool = True


class GraduationResponse(BaseModel):
    message: str
    graduated_at: datetime | None = None
    # True when the user owns a business, so the client prompts them to review
    # the pickup address (their campus address likely changed). No badge.
    needs_pickup_update: bool = False


# --- Public profiles / follow graph ------------------------------------


class PublicUserOut(BaseModel):
    """The single definition of what is public about an account.

    Deliberately NOT `UserOut`, which carries `email` — that schema describes
    an account to its own owner. Anything returned for *somebody else's*
    profile or in a followers list goes through here, so "what leaks" is one
    audited class rather than a judgement call at each endpoint.

    Also excluded on purpose: `id` (internal; `public_id` is the shareable
    one), `account_status`, `email_verified_at`, `failed_login_attempts` /
    `locked_until`, and `graduated_at` — graduation drives no badge, label, or
    chip anywhere in the product, so it has no business in a public payload.
    """

    model_config = ConfigDict(from_attributes=True)

    public_id: uuid.UUID
    username: str
    display_name: str
    bio: str | None = None
    account_type: str
    is_seller: bool = False
    # Denormalized so a client never has to fetch the organization separately:
    # a student's school, a business's own name.
    organization_name: str | None = None
    # A ready-to-render CDN URL, not a media id: the client should never have to
    # know the provider or how a derivative is built. None means "no photo" and
    # the caller draws the monogram (app/templates/partials/avatar.html).
    avatar_url: str | None = None

    @classmethod
    def from_user(cls, user) -> "PublicUserOut":
        """Build from a `User` ORM object. `organization_name` isn't a column,
        so it can't come from `model_validate` alone. Relies on
        `User.organization` being lazy="joined" — do not call this on a User
        loaded through a query that defers it, or the attribute access raises
        MissingGreenlet mid-request. The same applies to `profile_image`, which
        `avatar_url` reads through."""
        org = user.organization
        return cls(
            public_id=user.public_id,
            username=user.username,
            display_name=user.display_name,
            bio=user.bio,
            account_type=str(user.account_type),
            is_seller=bool(user.is_seller),
            organization_name=(org.short_name or org.official_name) if org else None,
            avatar_url=avatar_service.avatar_url(user, size="sm"),
        )


class FollowUserOut(PublicUserOut):
    """A followers/following row: the public account plus the *viewer's* own
    relationship to it, so each row's Follow button renders correctly without a
    request per row."""

    is_following: bool = False
    is_self: bool = False


class FollowResponse(BaseModel):
    """Result of a follow/unfollow toggle. `follower_count` is authoritative —
    the client should render it rather than incrementing locally, so two tabs
    can't drift."""

    following: bool
    follower_count: int
    # False when the request was a no-op (already in that state). The status is
    # still 200: a double-tapped toggle is not an error.
    changed: bool = True


class FollowListResponse(BaseModel):
    items: list[FollowUserOut]
    total: int


class AvatarResponse(BaseModel):
    """Result of a photo upload or removal.

    One shape for both, with `avatar_url = None` meaning "no photo" — so the
    client swaps an `<img src>` or falls back to the monogram from a single
    branch, and a removal needs no separate response type. The URL is a sized
    delivery derivative, already built server-side; the media id is never
    exposed, since nothing in the UI can do anything with it.
    """

    avatar_url: str | None = None


class ProfileUpdateRequest(BaseModel):
    """Edit Profile — the three identity fields plus the bio.

    CartFlow keeps three names apart on purpose, because they answer three
    different questions:

      ``username``     the handle. UNIQUE, and the only one that is, so it's the
                       identity every screen leads with. Changing it is allowed
                       here, and it moves the profile's URL (see below).
      ``display_name`` what you want to be called in public. NOT unique — any
                       number of people may be "Ada" — so it can never be the
                       thing we identify you by. Renders under the handle.
      ``full_name``    your real name. PRIVATE: receipts, delivery labels and
                       payouts need it; a public profile never shows it.

    **A username change moves the profile URL.** `/@{old}` stops resolving the
    moment the handle changes — nothing redirects, because nothing records that
    the old handle was ever this account's (doc §54 leaves that to a future
    `username_history` table). The UI says so before you save; the service just
    re-checks uniqueness and updates `username_normalized` in step.

    Every field is optional — the form submits only what changed, and the service
    applies exactly the keys that were present (``exclude_unset``). That
    distinction matters: an *absent* bio means "leave it alone", while an
    explicitly empty one means "clear it". Collapsing the two would make deleting
    a bio impossible. `full_name` behaves the same way.

    Lengths match the columns (username 30, display_name 150, full_name 150,
    bio 500) so a valid payload can never fail at the database.
    """

    model_config = ConfigDict(extra="ignore")

    username: str | None = Field(default=None, min_length=3, max_length=30)
    display_name: str | None = Field(default=None, max_length=150)
    full_name: str | None = Field(default=None, max_length=150)
    bio: str | None = Field(default=None, max_length=500)

    @field_validator("username")
    @classmethod
    def _check_username(cls, v: str | None) -> str | None:
        """Same rules as signup — charset, reserved words, no leading/trailing
        punctuation. Reusing the validator is the point: a handle you couldn't
        have signed up with must not be reachable by editing either."""
        if v is None:
            return None
        return validate_username_value(v)

    @field_validator("display_name")
    @classmethod
    def _require_a_real_name(cls, v: str | None) -> str | None:
        """A name of pure whitespace would blank the account's identity
        everywhere it renders, so it's rejected rather than normalized."""
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("Enter your name.")
        return v

    @field_validator("full_name")
    @classmethod
    def _normalize_full_name(cls, v: str | None) -> str | None:
        """Clearable, unlike display_name: an account is allowed to have told us
        no real name yet, and blank means exactly that."""
        if v is None:
            return None
        return v.strip() or None

    @field_validator("bio")
    @classmethod
    def _normalize_bio(cls, v: str | None) -> str | None:
        """Trim, and treat an all-whitespace bio as cleared — otherwise it
        stores as content and renders as a blank gap under the name."""
        if v is None:
            return None
        return v.strip() or None

    @model_validator(mode="after")
    def _something_to_save(self):
        # model_fields_set, not the values: `{"bio": ""}` is a real edit (clear
        # the bio) even though the normalized value is None.
        if not self.model_fields_set:
            raise ValueError("Nothing to save.")
        return self

