"""
Session model — server-side session store for cookie-based auth.

Per PRD 05-authentication-and-onboarding.md sec 13 + 22, and the
architectural decision to use HttpOnly cookie + server sessions for V1
(browser/server-rendered clients) rather than JWT (deferred to V2 for
mobile/public-API clients).

Only session_token_hash is persisted — the raw token lives in the
HttpOnly cookie and is never stored, matching the same pattern already
used for verification_tokens (see app/models/verification_token.py and
app/core/security.py's generate_session_token docstring).
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, UUIDPrimaryKeyMixin


def _as_utc(value: datetime) -> datetime:
    """Normalize a stored timestamp to a tz-aware UTC datetime.

    Timestamps are always written as UTC, but some backends (notably SQLite,
    used in the test harness) drop tzinfo on the round-trip and return a naive
    value. Postgres with ``DateTime(timezone=True)`` returns aware datetimes, so
    this is a no-op there. Treating a naive value as UTC keeps comparisons with
    ``datetime.now(timezone.utc)`` from raising.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


class Session(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)

    # SHA-256 hex digest of the raw session token (64 chars) — never the
    # raw value itself.
    session_token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)

    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)  # fits IPv4 + IPv6
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    last_activity: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) >= _as_utc(self.expires_at)

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    @property
    def is_active(self) -> bool:
        return not self.is_expired and not self.is_revoked

    def __repr__(self) -> str:
        return f"<Session user_id={self.user_id} active={self.is_active}>"
