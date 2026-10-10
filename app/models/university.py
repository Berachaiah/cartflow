
"""

University model.

Per PRD Chapter 12 sec 10 and Chapter 3 sec 6: university is a controlled

field — users select from a predefined dataset via search, and the FK

stores the university's id, not free-text. This keeps analytics/search

consistent and lets university data (names, aliases) be corrected later

without touching existing user records.

"""

import uuid

from datetime import datetime

from sqlalchemy import JSON, String

from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin

class University(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):

    __tablename__ = "universities"

    official_name: Mapped[str] = mapped_column(String(255), nullable=False)

    short_name: Mapped[str | None] = mapped_column(String(50), nullable=True)

    slug: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)

    state: Mapped[str | None] = mapped_column(String(100), nullable=True)

    institution_type: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # e.g. ["UNILAG", "University of Lagos"] — helps search match common

    # abbreviations without needing a separate join table for V1.

    aliases: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # Free-form provenance info (where this record was sourced/verified from),

    # per PRD Ch.12 sec 10 "source_metadata" — not surfaced to end users.

    source_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)

    def __repr__(self) -> str:

        return f"<University {self.short_name or self.official_name}>"

