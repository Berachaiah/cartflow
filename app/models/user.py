"""
User and follow-relationship models.

Per PRD Chapter 3 (User Accounts, Authentication, Onboarding, Profiles)
and Chapter 12 sec 10 (Core Identity Schema).

Design decisions made explicitly, since the product docs disagreed with
each other in places:
  - Administrators are NOT a third `account_type` here. Per the schema
    doc (21-database-schema.md sec 17) and Chapter 12, admins live in a
    separate `admin_users` table (not yet modeled) — kept fully apart
    from customer-facing accounts, matching both technical docs.
  - No `address` field. Chapter 3's own docx and Chapter 12's schema
    section never list one; treated as a stale field from an earlier
    draft rather than added speculatively.
  - Username case-insensitivity (Chapter 3 sec 8: "usernames are
    case-insensitive") is handled via a normalized, lowercased column
    with its own unique index — mirroring the same pattern the schema
    doc already uses for `hashtags.normalized_name` — rather than a
    dialect-specific collation, since this must work identically on
    both Postgres and MySQL per our dialect-agnostic engine.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, PublicIdMixin, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class AccountType(str, enum.Enum):
    """The account's *persona* — descriptive, and stable for the account's
    life. Deliberately NOT the same axis as "can this account sell": selling
    is a capability (see `User.is_seller`), because a STUDENT can start a
    business without ceasing to be a student. Stored as a plain String(20),
    so adding a member here needs no DB migration."""

    STUDENT = "student"
    INDIVIDUAL = "individual"
    BUSINESS = "business"


class AccountStatus(str, enum.Enum):
    """Per PRD Chapter 3 sec 10. Enforced server-side — never trust a
    frontend check for status-gated actions (e.g. suspended users must
    be blocked from login at the auth-dependency level, not just hidden
    UI)."""

    ACTIVE = "active"
    PENDING_VERIFICATION = "pending_verification"
    RESTRICTED = "restricted"
    SUSPENDED = "suspended"
    DELETED = "deleted"


class User(Base, UUIDPrimaryKeyMixin, PublicIdMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("length(username) >= 3", name="ck_users_username_min_length"),
        CheckConstraint("length(username) <= 30", name="ck_users_username_max_length"),
    )

    account_type: Mapped[AccountType] = mapped_column(
        String(20), nullable=False, default=AccountType.STUDENT
    )
    account_status: Mapped[AccountStatus] = mapped_column(
        String(30), nullable=False, default=AccountStatus.PENDING_VERIFICATION
    )

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    # Nullable since the Google-OAuth flow creates passwordless accounts:
    # such a user proves identity via Google, never a local password. A NULL
    # hash therefore means "no local login" — verify_password is never called
    # on it (login looks the user up and would return the generic failure).
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Google account subject ("sub") — the stable, unique per-Google-account
    # identifier. Set only for accounts that have linked Google. Matched first
    # (before email) when a returning Google user signs in, so a user who later
    # changes their Google email still resolves to the same CartFlow account.
    google_sub: Mapped[str | None] = mapped_column(
        String(255), unique=True, index=True, nullable=True
    )

    # Display casing is preserved as typed by the user (e.g. "JaneDoe");
    # uniqueness/lookups go through username_normalized instead.
    username: Mapped[str] = mapped_column(String(30), nullable=False)
    username_normalized: Mapped[str] = mapped_column(
        String(30), unique=True, index=True, nullable=False
    )

    # Three distinct identity fields, each with a different job:
    #
    #   username      the handle. UNIQUE, and the only one that is. This is the
    #                 identity the app leads with, everywhere.
    #   display_name  what you want to be called in public. NOT unique — any
    #                 number of accounts may be "Ada". Shown under the handle.
    #   full_name     your real name. PRIVATE: it goes on receipts, delivery and
    #                 payouts, and is never rendered on a public profile.
    #
    # full_name is nullable because accounts created before it existed only ever
    # had the signup name folded into display_name — migration 0008 backfills
    # from there, but a NULL is still a legitimate "we were never told".
    display_name: Mapped[str] = mapped_column(String(150), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    bio: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # The profile photo. ON DELETE SET NULL, not CASCADE: losing an image must
    # never take the account with it — the user simply falls back to the drawn
    # monogram (app/templates/partials/avatar.html).
    profile_image_media_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("media.id", ondelete="SET NULL"), nullable=True
    )
    # Eager-loaded for the same reason `organization` is: PublicUserOut.from_user
    # reads through this relationship, and a lazy load outside the original
    # greenlet context raises MissingGreenlet under async SQLAlchemy.
    profile_image: Mapped["Media | None"] = relationship(
        lazy="joined", foreign_keys=[profile_image_media_id]
    )

    # V1 pivot: users belong to an Organization (universities are folded into
    # `organizations` by migration 0002). `organization_id` preserves the same
    # UUIDs the old `university_id` held, so the fold-in backfill is a straight
    # copy. See app/models/organization.py.
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True
    )
    # foreign_keys pinned explicitly: Organization now also has a FK back to
    # users (organizations.owner_user_id), so there are two FK paths between the
    # tables and SQLAlchemy can't infer which one this relationship rides on.
    organization: Mapped["Organization"] = relationship(
        lazy="joined", foreign_keys=[organization_id]
    )

    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Presence, for messaging's "Active now / last seen" (doc 10 §19).
    #
    # Written when a messaging WebSocket connects or disconnects and when a
    # message is sent — NOT on every request, which would turn each page view
    # into a write. So it means "last seen in a live session", and a user reading
    # the feed with no socket open goes stale, which is the honest reading of a
    # presence timestamp anyway.
    #
    # "Online" is not stored: it is membership of the in-process socket registry
    # (app/routers/ws.py). A boolean column would survive a crash and report
    # everyone as online forever.
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Capability flag, denormalized from "does this user own a Business org"
    # (organizations.owner_user_id == this user). Kept in sync by the signup /
    # business-upgrade services so view-gating (posts + Business Hub require a
    # seller; everyone can post stories) is a cheap boolean read, not a join.
    is_seller: Mapped[bool] = mapped_column(default=False, nullable=False)

    # Staff flag, not an account type. The admin console is a capability on top
    # of an ordinary account (docs 12 §7 keeps `account_type` to student /
    # business / organisation), so promoting someone does not change how they
    # appear to anyone else — it only unlocks /admin. Never derived from the
    # username: a flag in the row is auditable, a magic name is a backdoor.
    is_admin: Mapped[bool] = mapped_column(default=False, nullable=False, server_default="0")

    # Set when a student self-marks as graduated. Purely informational — it
    # does NOT gate login or drive any "alumni/graduate" badge (there is none).
    # Its one behavioural effect: a graduated seller is prompted to update the
    # pickup address on their business, since a campus address likely changed.
    graduated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Brute-force / credential-stuffing defence for PASSWORD login (session.py).
    # failed_login_attempts counts consecutive wrong passwords and resets to 0 on
    # a success; when it crosses the threshold, locked_until is set and login is
    # refused until that time passes — even for the correct password. Only the
    # local-password path touches these (Google sign-in is passwordless and never
    # reaches the password check), so a locked account can still sign in with
    # Google. server_default 0 mirrors the migration so raw inserts are safe.
    failed_login_attempts: Mapped[int] = mapped_column(
        default=0, server_default="0", nullable=False
    )
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    @property
    def is_business(self) -> bool:
        return self.account_type == AccountType.BUSINESS

    @property
    def is_verified(self) -> bool:
        return self.email_verified_at is not None

    @property
    def is_graduated(self) -> bool:
        return self.graduated_at is not None

    def __repr__(self) -> str:
        return f"<User @{self.username} ({self.account_type})>"


class UserFollow(Base, TimestampMixin):
    """Per PRD schema doc sec 4 'follows' / Chapter 12 sec 10 'user_follows'.
    Pure association table — no soft delete (unfollow is a hard delete of
    the row), no UUID PK needed since (follower_id, following_id) is
    already a natural unique key.
    """

    __tablename__ = "user_follows"
    __table_args__ = (
        UniqueConstraint("follower_id", "following_id", name="uq_user_follows_pair"),
    )

    follower_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), primary_key=True
    )
    # Indexed on its own: the composite PK (follower_id, following_id) only
    # serves follower_id-leading lookups ("who does X follow"), so every
    # followers-direction query — including the follower COUNT on every profile
    # render — would otherwise scan the table. See migration 0006.
    following_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), primary_key=True, index=True
    )
