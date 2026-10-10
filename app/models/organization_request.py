"""
Organization request + deferred signup models (spec items #6/#7).

When a user signs up but their institution isn't in the directory, we don't
fail the flow — we capture:
  - an `OrganizationRequest` (the institution to add), and
  - a `SignupRequest` (their account, password already hashed), held until an
    admin approves the organization.

On approval the Organization Service creates/links the organization, then
completes the pending signup — creating the real account and sending the
verification email — so the user never has to register again (spec item #6).

`OrganizationRequest.reviewed_by` is a bare UUID with no FK: the `admin_users`
table isn't modeled yet, mirroring `User.profile_image_media_id`. Add the FK
once `app/models/admin.py` exists.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class RequestStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class SignupRequestStatus(str, enum.Enum):
    """`approved` = its organization request was approved and the org exists;
    `completed` = the real user account has since been created from it. The
    two-step split lets approval and account-creation fail independently."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    COMPLETED = "completed"


class OrganizationRequest(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A user-submitted "please add my institution" record, pending admin
    review. On approval it links to the organization that was created."""

    __tablename__ = "organization_requests"

    requested_name: Mapped[str] = mapped_column(String(255), nullable=False)
    country: Mapped[str] = mapped_column(String(100), nullable=False, default="Nigeria")
    state: Mapped[str | None] = mapped_column(String(100), nullable=True)

    organization_type_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organization_types.id"), nullable=True
    )

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=RequestStatus.PENDING.value, index=True
    )

    resulting_organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True
    )

    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<OrganizationRequest {self.requested_name!r} ({self.status})>"


class SignupRequest(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A deferred student signup, parked until its `OrganizationRequest` is
    approved. The password is already Argon2-hashed here — the raw password is
    never stored, exactly as in the immediate-signup path."""

    __tablename__ = "signup_requests"

    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(30), nullable=False)
    username_normalized: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    organization_request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organization_requests.id"), nullable=False, index=True
    )

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=SignupRequestStatus.PENDING.value, index=True
    )

    # Set once the deferred signup is completed into a real account.
    resulting_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    def __repr__(self) -> str:
        return f"<SignupRequest {self.email} ({self.status})>"
