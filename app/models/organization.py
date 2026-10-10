"""
Organization models — the platform's core taxonomy (spec items #1/#2).

Replaces the single `universities` table with a three-level hierarchy:

    OrganizationGroup   (Education, Business, Government, Non-Profit, Other)
        └── OrganizationType   (University, Polytechnic, ... | Startup, SME, ...)
                └── Organization   (a concrete institution / entity)

Universities become Organizations of type "University" under the "Education"
group. The V1 frontend still only exposes Universities (spec item #23); the
backend already supports the full hierarchy.

Every column on the old `University` model is preserved on `Organization`
(official_name, short_name, slug, state, aliases, source_metadata, status) so
the fold-in migration is loss-free — plus `organization_type_id` and
`country` (the directory's country filter, spec item #4; existing data is all
Nigeria).
"""

import enum
import uuid

from sqlalchemy import ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class OrganizationStatus(str, enum.Enum):
    """Mirrors the old University.status vocabulary. `unverified` marks rows
    created from user-submitted names (get_or_create, or an approved request)
    pending admin review; `active` marks curated/verified rows."""

    ACTIVE = "active"
    UNVERIFIED = "unverified"


class OrganizationGroup(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Top-level taxonomy bucket. Small, curated, config-like — seeded by the
    0002 migration, not user-editable at runtime."""

    __tablename__ = "organization_groups"

    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    types: Mapped[list["OrganizationType"]] = relationship(back_populates="group")

    def __repr__(self) -> str:
        return f"<OrganizationGroup {self.slug}>"


class OrganizationType(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Subtype within a group (e.g. University under Education). `slug` is
    unique per-group, not globally, so different groups could reuse a label."""

    __tablename__ = "organization_types"
    __table_args__ = (
        UniqueConstraint("organization_group_id", "slug", name="uq_org_type_group_slug"),
    )

    organization_group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organization_groups.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    group: Mapped["OrganizationGroup"] = relationship(back_populates="types")

    def __repr__(self) -> str:
        return f"<OrganizationType {self.slug}>"


class Organization(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """A concrete organization (a university, in V1). Superset of the old
    University model — the fold-in migration copies every University row here,
    preserving its primary key so `users.university_id` values still resolve."""

    __tablename__ = "organizations"

    organization_type_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organization_types.id"), nullable=True, index=True
    )

    official_name: Mapped[str] = mapped_column(String(255), nullable=False)
    short_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    slug: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)

    country: Mapped[str] = mapped_column(String(100), nullable=False, default="Nigeria")
    state: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Education-specific ownership class carried over verbatim from the old
    # University model (federal / state / private). Nullable — non-education
    # organizations leave it unset. Kept as a column (not folded into JSON) so
    # the fold-in migration is a plain INSERT...SELECT and the value stays
    # queryable.
    institution_type: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # e.g. ["UNILAG", "University of Lagos"] — abbreviations + alternate names,
    # used by search so common shorthands match without a separate join table.
    aliases: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # Free-form provenance (where this record was sourced/verified from) —
    # never surfaced to end users.
    source_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=OrganizationStatus.ACTIVE.value
    )

    # The user who owns this organization as a seller (set for Business-group
    # orgs created at signup or via "Start selling"). Source of truth for the
    # selling capability; `users.is_seller` is the denormalized mirror. Nullable
    # because curated/education orgs (universities) have no single owner.
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )

    # Where buyers collect orders from this business. Editable in the Business
    # Hub. A seller who marks themselves graduated is prompted to update this,
    # since a campus pickup point likely no longer applies.
    pickup_address: Mapped[str | None] = mapped_column(String(500), nullable=True)

    type: Mapped["OrganizationType | None"] = relationship(lazy="joined")

    def __repr__(self) -> str:
        return f"<Organization {self.short_name or self.official_name}>"
