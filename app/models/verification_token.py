"""
Verification token model.

Per PRD Chapter 3 sec 9 (Email Verification): supports resending,
expiring old tokens, and replacing old tokens when a new one is issued.
`purpose` lets this one table also serve password-reset tokens
(Chapter 3 sec 8 requires the same properties: random, expiring,
single-use, stored as a hash) without a second near-identical table.

Password reset offers the user TWO ways to prove they own the mailbox,
and both are carried by a SINGLE row:

  token_hash  -> the emailed reset *link*  (32 random bytes)
  otp_hash    -> the emailed 6-digit *code*

One row rather than two is what keeps the invariants honest: the pair
shares one `expires_at` and one `used_at`, so using either path burns
the other. Two rows could drift out of sync and leave a live credential
behind after a reset.

Only hashes are ever stored — never the raw token or the raw OTP —
mirroring the pattern established for session tokens
(app/core/security.py: generate_session_token docstring).
"""

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

# A 6-digit code has only 10^6 possibilities, so it is brute-forceable in
# minutes without a cap. Five wrong guesses burns the token and forces the
# user to request a fresh one.
MAX_OTP_ATTEMPTS = 5


class TokenPurpose(str, enum.Enum):
    EMAIL_VERIFICATION = "email_verification"
    PASSWORD_RESET = "password_reset"


class VerificationToken(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "verification_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    purpose: Mapped[TokenPurpose] = mapped_column(String(30), nullable=False)

    # SHA-256 hex digest of the raw token — the raw value is only ever
    # in the email link, never persisted.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)

    # SHA-256 hex digest of the 6-digit OTP. Null for email-verification
    # rows, which have no code path. NOT unique: distinct users can easily
    # draw the same six digits, and a unique index would make the second
    # one fail to insert.
    otp_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    # Wrong OTP guesses against this row. See MAX_OTP_ATTEMPTS.
    otp_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def is_expired(self) -> bool:
        # SQLite hands back naive datetimes even from a timezone=True column,
        # so compare in UTC either way rather than trusting tzinfo to be set.
        expires = self.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) >= expires

    @property
    def is_used(self) -> bool:
        return self.used_at is not None

    @property
    def otp_attempts_exceeded(self) -> bool:
        return self.otp_attempts >= MAX_OTP_ATTEMPTS

    @property
    def is_usable(self) -> bool:
        """A row that can still be redeemed by either path."""
        return not self.is_used and not self.is_expired and not self.otp_attempts_exceeded

    def __repr__(self) -> str:
        return f"<VerificationToken {self.purpose} user_id={self.user_id}>"
