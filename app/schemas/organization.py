"""Organization request/response schemas (spec item #22)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class OrganizationGroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    sort_order: int


class OrganizationTypeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_group_id: uuid.UUID
    name: str
    slug: str
    sort_order: int


class OrganizationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_type_id: uuid.UUID | None = None
    official_name: str
    short_name: str | None = None
    slug: str
    country: str
    state: str | None = None
    institution_type: str | None = None
    status: str
    # `source_metadata` is intentionally NOT exposed (provenance is internal,
    # per app/models/organization.py).
    type: OrganizationTypeOut | None = None


class OrganizationDirectoryPage(BaseModel):
    """Paginated directory envelope (spec item #4). Success responses are
    returned bare (the {data, meta} wrapper in Ch.12 sec 48 is applied only
    to errors in this codebase — matches the universities router)."""

    items: list[OrganizationOut]
    total: int
    page: int
    per_page: int
    pages: int


class OrganizationResolveRequest(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    type: str | None = Field(
        default="university",
        description="Organization type slug to scope resolution to (V1: university).",
    )


class OrganizationResolveResponse(BaseModel):
    """Read-only resolution used by the new signup UX: `found=False` means the
    caller should offer 'browse directory / request new' rather than the API
    silently creating a row (spec item #6, deferred-request flow)."""

    organization: OrganizationOut | None = None
    found: bool


class OrganizationRequestCreate(BaseModel):
    requested_name: str = Field(min_length=2, max_length=255)
    country: str = Field(default="Nigeria", max_length=100)
    state: str | None = Field(default=None, max_length=100)
    type: str | None = Field(
        default=None, description="Organization type slug (optional)."
    )


class OrganizationRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    requested_name: str
    country: str
    state: str | None = None
    organization_type_id: uuid.UUID | None = None
    status: str
    created_at: datetime


# --- The business a user owns (Business Hub) ----------------------------


class BusinessProfileOut(BaseModel):
    """The seller's own business, as the Business Hub reads and writes it.

    Deliberately narrower than `OrganizationOut`: only the fields the Hub can
    actually show or edit today. `slug` is included read-only so a client can
    tell that renaming does not move the row (see the note on
    `BusinessProfileUpdateRequest`), and `owner_user_id` is omitted — the only
    caller is the owner, so echoing their own id back is noise.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    official_name: str
    short_name: str | None = None
    slug: str
    state: str | None = None
    country: str
    pickup_address: str | None = None
    status: str


class BusinessProfileUpdateRequest(BaseModel):
    """Business Hub → Operations / Settings edits.

    Only three fields, because only three exist. Doc 16 §26 also lists Logo,
    Username, Bio, Website, Delivery Coverage and Contact — `organizations` has
    no column for any of them (no Media model either), so they are not accepted
    here rather than accepted and silently dropped.

    Each field is optional and applied only when present (`exclude_unset`), the
    same partial-update contract as `ProfileUpdateRequest`: an absent
    `pickup_address` leaves the current one alone, while an explicitly empty one
    clears it. That distinction is the whole point of this endpoint — a
    graduated seller whose campus pickup point no longer exists needs to be able
    to remove it, not just overwrite it.

    `slug` is intentionally NOT re-derived when the name changes. It is unique
    across every organization, so re-slugging would have to resolve collisions
    against curated universities, and nothing routes to a business by slug (a
    business is reached at `/@username`). The row keeps the slug it was created
    with.
    """

    model_config = ConfigDict(extra="ignore")

    business_name: str | None = Field(default=None, min_length=2, max_length=255)
    state: str | None = Field(default=None, max_length=100)
    pickup_address: str | None = Field(default=None, max_length=500)

    @field_validator("business_name")
    @classmethod
    def _require_a_real_name(cls, v: str | None) -> str | None:
        """A whitespace-only name would blank the shop everywhere it renders."""
        if v is None:
            return None
        v = v.strip()
        if len(v) < 2:
            raise ValueError("Enter your business name.")
        return v

    @field_validator("state", "pickup_address")
    @classmethod
    def _blank_to_null(cls, v: str | None) -> str | None:
        """Trim, and store an all-whitespace value as cleared — otherwise it
        renders as a blank line under the business name."""
        if v is None:
            return None
        v = v.strip()
        return v or None


class BusinessProfileResponse(BaseModel):
    message: str
    business: BusinessProfileOut
