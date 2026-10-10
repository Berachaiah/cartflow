"""
Email verification service.

Per PRD Chapter 3 sec 9:
  1. User registers -> account created unverified (handled in auth.py's
     signup_student; this module picks up from step 3 onward).
  2. System generates a secure verification token.
  3. Verification email is sent.
  4. User opens the verification link.
  5. Token is validated.
  6. Account email is marked verified.

Also implements the required supporting behavior:
  - Resending verification emails.
  - Expiring old tokens.
  - Replacing old tokens when a new one is issued (any prior unused
    email_verification token for the user is invalidated when a new one
    is generated, so only the most recently sent link ever works).
  - Rate limiting resend requests (a minimum interval between sends,
    enforced here rather than at the router, since it's a business rule).

Token handling: the raw token only ever exists in memory and in the
emailed link. Only its SHA-256 hash is persisted (VerificationToken.token_hash),
matching the pattern in app/core/security.py's generate_session_token docstring.
"""

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.email_templates import render_email
from app.core.exceptions import ConflictError, NotFoundError, RateLimitedError, ValidationAppError
from app.core.security import hash_token
from app.core.timeutils import ensure_utc
from app.integrations.smtp_client import send_email
from app.models.user import User
from app.models.verification_token import TokenPurpose, VerificationToken

settings = get_settings()

TOKEN_TTL = timedelta(hours=24)
RESEND_COOLDOWN = timedelta(minutes=2)


def _hash_token(raw_token: str) -> str:
    # Thin alias kept so existing call sites read unchanged; the single
    # implementation now lives in core.security alongside the other
    # crypto primitives and is shared with the password-reset service.
    return hash_token(raw_token)


async def _invalidate_prior_tokens(db: AsyncSession, user_id, purpose: TokenPurpose) -> None:
    """Marks any existing unused tokens of this purpose for this user as
    used, so only the newest one is valid (Chapter 3 sec 9: "replacing old
    tokens when a new one is issued")."""
    stmt = select(VerificationToken).where(
        VerificationToken.user_id == user_id,
        VerificationToken.purpose == purpose,
        VerificationToken.used_at.is_(None),
    )
    result = await db.execute(stmt)
    now = datetime.now(timezone.utc)
    for token in result.scalars().all():
        token.used_at = now


async def send_verification_email(db: AsyncSession, user: User) -> None:
    """Generates a fresh token (invalidating any prior unused one) and
    emails the verification link. Does NOT enforce the resend cooldown —
    call this directly at signup; use request_verification_resend for
    the user-facing "resend" action, which does enforce it."""
    await _invalidate_prior_tokens(db, user.id, TokenPurpose.EMAIL_VERIFICATION)

    raw_token = secrets.token_urlsafe(32)
    token_hash = _hash_token(raw_token)
    expires_at = datetime.now(timezone.utc) + TOKEN_TTL

    verification_token = VerificationToken(
        user_id=user.id,
        purpose=TokenPurpose.EMAIL_VERIFICATION,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    db.add(verification_token)
    await db.flush()

    verify_url = f"{settings.APP_BASE_URL}/verify-email?token={raw_token}"
    html = render_email(
        "verify_email.html",
        display_name=user.display_name,
        verify_url=verify_url,
        expires_hours=int(TOKEN_TTL.total_seconds() // 3600),
    )

    await send_email(to=user.email, subject="Verify your CartFlow email", html=html)


async def request_verification_resend(db: AsyncSession, user: User) -> None:
    """User-facing resend action — enforces a cooldown between sends
    (Chapter 3 sec 9: 'Rate limiting resend requests')."""
    if user.email_verified_at is not None:
        raise ConflictError("This email is already verified.")

    stmt = (
        select(VerificationToken)
        .where(
            VerificationToken.user_id == user.id,
            VerificationToken.purpose == TokenPurpose.EMAIL_VERIFICATION,
        )
        .order_by(VerificationToken.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    last_token = result.scalar_one_or_none()

    if last_token is not None:
        # ensure_utc: created_at comes back naive from SQLite, and
        # subtracting it from an aware `now` raises TypeError.
        elapsed = datetime.now(timezone.utc) - ensure_utc(last_token.created_at)
        if elapsed < RESEND_COOLDOWN:
            wait_seconds = int((RESEND_COOLDOWN - elapsed).total_seconds())
            raise RateLimitedError(
                f"Please wait {wait_seconds} seconds before requesting another verification email."
            )

    await send_verification_email(db, user)


async def verify_email_token(db: AsyncSession, raw_token: str) -> User:
    """Validates a raw token from the verification link, marks the
    account's email verified, and marks the token used.

    Idempotent by design. `used_at` gets stamped in two different
    situations and they must not produce the same answer:

      - the link already did its job (the user clicked twice, or a mail
        client prefetched it) -> succeed silently, the email IS verified;
      - the link was superseded by a newer send and the account is still
        unverified -> fail, and say which link to use.

    Collapsing both into "already used" would tell someone their email is
    verified when it isn't, and leave them with no way to notice.
    """
    token_hash = _hash_token(raw_token)

    stmt = select(VerificationToken).where(
        VerificationToken.token_hash == token_hash,
        VerificationToken.purpose == TokenPurpose.EMAIL_VERIFICATION,
    )
    result = await db.execute(stmt)
    token = result.scalar_one_or_none()

    if token is None:
        raise NotFoundError("This verification link is invalid.")

    user_stmt = select(User).where(User.id == token.user_id)
    user_result = await db.execute(user_stmt)
    user = user_result.scalar_one_or_none()
    if user is None:
        raise NotFoundError("Account not found.")

    if token.is_used:
        if user.email_verified_at is not None:
            return user
        raise ValidationAppError(
            "This verification link was replaced by a newer one. "
            "Please open the most recent email we sent you."
        )
    if token.is_expired:
        raise ValidationAppError("This verification link has expired. Please request a new one.")

    user.email_verified_at = datetime.now(timezone.utc)
    token.used_at = datetime.now(timezone.utc)

    return user
