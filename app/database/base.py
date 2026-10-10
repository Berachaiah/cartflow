"""
Declarative base and shared model mixins.

Per PRD Chapter 12, section 9 "Database Design Principles":
  - UUIDs (or non-sequential public identifiers) for externally visible resources.
  - Timestamps stored in UTC, timezone-aware.
  - Soft deletion / archival for important records.
  - Audit records are append-only.

Every domain model (app/models/*.py) should inherit `Base` plus whichever
mixins apply. Not every table needs every mixin — e.g. `user_follows` is a
pure association table and doesn't get `SoftDeleteMixin`; `audit_logs` is
append-only and doesn't get `TimestampMixin`'s `updated_at`.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy import Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Root declarative base for all CartFlow ORM models."""
    pass


class UUIDPrimaryKeyMixin:
    """Internal UUID primary key, per PRD Ch.12 sec 9-10 ('id UUID primary key')."""

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )


class PublicIdMixin:
    """Separate externally-shareable identifier, distinct from the internal PK.

    Several PRD tables (users, posts, orders, tickets, ...) list both `id`
    and `public_id`. Keeping them distinct means internal PKs never need to
    be treated as a security boundary, and public IDs can be reissued /
    reformatted without touching relationships.
    """

    public_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), unique=True, index=True, default=uuid.uuid4
    )


class TimestampMixin:
    """created_at / updated_at, timezone-aware, UTC (PRD Ch.12 sec 9)."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SoftDeleteMixin:
    """Nullable deleted_at for recoverable soft deletion (PRD Ch.12 sec 9,
    applies to: users, businesses, products, posts, events, ...).
    """

    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None
