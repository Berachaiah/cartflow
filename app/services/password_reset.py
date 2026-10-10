"""
Password-reset service — link and OTP, one token row behind both.

The user's locked decision: "when someone chooses forget password, it then
sends the reset password link and also the otp to their email, so whichever
the user chooses to use". So a single request emails BOTH credentials, and
redeeming either one burns the other.

Security properties this module is responsible for, and why each is here
rather than left to the router:

1. NO ACCOUNT ENUMERATION. request_password_reset() returns the same
   response whether or not the identifier matched. An attacker must not be
   able to use this endpoint as a "does this email/username exist?" oracle.
   The only observable difference is whether an email lands in a mailbox
   they don't control.

2. HASHES ONLY. The raw token and the raw OTP exist just long enough to be
   put in the email body. A database dump gives an attacker nothing usable.

3. SINGLE USE, SHARED FATE. Link and OTP share one row, so one `used_at`
   stamp kills both paths. Two rows could drift and leave a live credential
   behind after a completed reset.

4. OTP BRUTE-FORCE CAP. 10^6 possibilities falls in minutes to an
   unthrottled attacker. Five wrong guesses burn the row.

5. SESSION REVOCATION ON RESET. Whoever knew the old password loses access
   immediately. A reset that leaves existing sessions alive doesn't lock an
   intruder out, which is the main reason people reset in the first place.

6. TIMING-SAFE COMPARISON. Hash lookups go through the DB by hash, and the
   OTP check uses constant_time_compare, so response timing doesn't leak how
   much of a credential was correct.

7. SUPERSEDE ON RE-REQUEST. Asking again invalidates the previous row, so
   there is never a pile of concurrently-valid codes for one account.

8. THE COOLDOWN IS SILENT. Re-requesting inside RESEND_COOLDOWN returns the
   same generic message instead of a 429. A distinguishable rate-limit
   response would reintroduce the property-1 oracle at the cost of two
   requests: 429 on the second POST means the account exists, 200 means it
   doesn't. Suppressing the send is the security control; announcing it is
   not.
"""

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.email_templates import render_email
from app.core.exceptions import ValidationAppError
from app.core.security import (
    constant_time_compare,
    generate_otp,
    hash_password,
    hash_token,
    verify_password,
)
from app.integrations.smtp_client import send_email
from app.models.session import Session
from app.models.user import AccountStatus, User
from app.models.verification_token import (
    MAX_OTP_ATTEMPTS,
    TokenPurpose,
    VerificationToken,
)

settings = get_settings()

# Short by design. A reset credential sitting in an inbox is a standing key
# to the account, and both paths are delivered together.
RESET_TTL = timedelta(minutes=30)

# Throttle per account, so re-requesting can't be used to mail-bomb someone
# or to churn through OTP space by forcing fresh codes.
RESEND_COOLDOWN = timedelta(seconds=60)

# Same statuses that are barred from logging in are barred from resetting.
# Letting a suspended account reset its way back in would route around the
# suspension.
BLOCKED_RESET_STATUSES = {AccountStatus.SUSPENDED, AccountStatus.DELETED}

GENERIC_RESET_RESPONSE = (
    "If that account exists, we've sent a reset link and a code to its email "
    "address. Both expire in 30 minutes."
)

# One message for every failure mode of redemption. Telling the user which
# of expired / already-used / wrong / locked applies would let an attacker
# probing a stolen link learn things about the account.
INVALID_CREDENTIAL_MESSAGE = (
    "That reset link or code is invalid or has expired. Request a new one to "
    "try again."
)


def _aware(value: datetime) -> datetime:
    """Force a UTC tzinfo onto a DB datetime.

    SQLite returns naive datetimes even from a timezone=True column, so
    comparing a stored value against now(timezone.utc) raises TypeError
    under tests while working fine on Postgres. Normalizing here keeps the
    comparison correct on both.
    """
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


async def _find_user_by_identifier(db: AsyncSession, identifier: str) -> User | None:
    """Resolve a username OR an email to a user.

    Mirrors login's identifier handling so "forgot password" accepts exactly
    what the login form accepts. Both lookups are case-insensitive against
    the normalized columns.
    """
    needle = identifier.strip().lower()
    if not needle:
        return None

    result = await db.execute(
        select(User).where(
            (User.email == needle) | (User.username_normalized == needle)
        )
    )
    return result.scalar_one_or_none()


async def _latest_reset_token(db: AsyncSession, user_id) -> VerificationToken | None:
    result = await db.execute(
        select(VerificationToken)
        .where(
            VerificationToken.user_id == user_id,
            VerificationToken.purpose == TokenPurpose.PASSWORD_RESET,
        )
        .order_by(VerificationToken.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def request_password_reset(db: AsyncSession, identifier: str) -> str:
    """Email a reset link + OTP for `identifier` (username or email).

    Returns the generic message for every outcome. Callers must not branch
    on the result — see property 1 in the module docstring.
    """
    user = await _find_user_by_identifier(db, identifier)

    if user is None or user.account_status in BLOCKED_RESET_STATUSES:
        # Deliberately silent. Same return value, no email sent.
        return GENERIC_RESET_RESPONSE

    existing = await _latest_reset_token(db, user.id)
    if existing is not None and existing.is_usable:
        age = datetime.now(timezone.utc) - _aware(existing.created_at)
        if age < RESEND_COOLDOWN:
            # Swallowed into the generic response rather than raised as a
            # 429. A distinguishable rate-limit reply would rebuild the
            # very oracle property 1 exists to prevent: POST twice for any
            # identifier — 429 on the second means the account is real,
            # 200 means it isn't. The user loses nothing, because the
            # message they see is the same one that told them to check
            # their email, and the email they're waiting for is already
            # in flight.
            return GENERIC_RESET_RESPONSE

    # Supersede every earlier reset row for this user (property 7). Deleting
    # rather than marking used keeps the table from growing without bound,
    # and an expired reset row has no audit value worth retaining.
    await db.execute(
        delete(VerificationToken).where(
            VerificationToken.user_id == user.id,
            VerificationToken.purpose == TokenPurpose.PASSWORD_RESET,
        )
    )

    raw_token = secrets.token_urlsafe(32)
    otp_code = generate_otp()

    db.add(
        VerificationToken(
            user_id=user.id,
            purpose=TokenPurpose.PASSWORD_RESET,
            token_hash=hash_token(raw_token),
            otp_hash=hash_token(otp_code),
            otp_attempts=0,
            expires_at=datetime.now(timezone.utc) + RESET_TTL,
        )
    )
    await db.commit()

    base = settings.APP_BASE_URL.rstrip("/")
    html = render_email(
        "password_reset.html",
        display_name=user.display_name,
        reset_url=f"{base}/reset-password?token={raw_token}",
        forgot_url=f"{base}/forgot-password",
        otp_code=otp_code,
        expires_minutes=int(RESET_TTL.total_seconds() // 60),
        max_attempts=MAX_OTP_ATTEMPTS,
    )

    # Send AFTER the commit. If the mail server is down we must not leave a
    # committed token the user never received; if the commit fails we must
    # not have already mailed a credential that no longer exists.
    await send_email(
        to=user.email,
        subject="Reset your CartFlow password",
        html=html,
    )

    return GENERIC_RESET_RESPONSE


async def _resolve_by_token(db: AsyncSession, raw_token: str) -> VerificationToken | None:
    """Look a reset row up by its emailed link token."""
    result = await db.execute(
        select(VerificationToken).where(
            VerificationToken.token_hash == hash_token(raw_token),
            VerificationToken.purpose == TokenPurpose.PASSWORD_RESET,
        )
    )
    return result.scalar_one_or_none()


async def _resolve_by_otp(
    db: AsyncSession, identifier: str, otp_code: str
) -> VerificationToken | None:
    """Look a reset row up by identifier + OTP, counting wrong guesses.

    The OTP is scoped to an identifier rather than searched globally: with
    enough accounts in the table, some user somewhere will have the code
    `000123`, and a global lookup would let an attacker reset a random
    stranger's password by guessing digits alone.

    A wrong guess increments otp_attempts and commits, so the cap holds
    across requests (property 4).
    """
    user = await _find_user_by_identifier(db, identifier)
    if user is None or user.account_status in BLOCKED_RESET_STATUSES:
        return None

    token = await _latest_reset_token(db, user.id)
    if token is None or token.otp_hash is None:
        return None

    if not token.is_usable:
        return None

    if not constant_time_compare(token.otp_hash, hash_token(otp_code)):
        token.otp_attempts += 1
        await db.commit()
        return None

    return token


async def verify_reset_credential(
    db: AsyncSession,
    *,
    token: str | None = None,
    identifier: str | None = None,
    otp_code: str | None = None,
) -> VerificationToken:
    """Validate a link token OR an identifier+OTP pair without consuming it.

    Used by the reset page to check a credential up front, so the user finds
    out a stale link is stale before typing a new password twice. Raises
    ValidationAppError with one generic message on every failure path.
    """
    if token:
        record = await _resolve_by_token(db, token)
    elif identifier and otp_code:
        record = await _resolve_by_otp(db, identifier, otp_code)
    else:
        raise ValidationAppError(
            "Provide either a reset token or your username/email plus the code."
        )

    if record is None or not record.is_usable:
        raise ValidationAppError(INVALID_CREDENTIAL_MESSAGE)

    return record


async def reset_password(
    db: AsyncSession,
    *,
    new_password: str,
    token: str | None = None,
    identifier: str | None = None,
    otp_code: str | None = None,
) -> User:
    """Consume a reset credential and set a new password.

    Accepts either path. On success: the token row is burned, the password
    hash is replaced, and every existing session for the user is deleted.
    """
    record = await verify_reset_credential(
        db, token=token, identifier=identifier, otp_code=otp_code
    )

    user = await db.get(User, record.user_id)
    if user is None or user.account_status in BLOCKED_RESET_STATUSES:
        # The account was suspended or deleted between issue and redemption.
        raise ValidationAppError(INVALID_CREDENTIAL_MESSAGE)

    # Reusing the current password defeats the point of the reset — commonly
    # the user is resetting BECAUSE the old one leaked.
    if verify_password(new_password, user.password_hash):
        raise ValidationAppError(
            "Choose a password you haven't used on this account before."
        )

    user.password_hash = hash_password(new_password)
    record.used_at = datetime.now(timezone.utc)

    # Property 5: revoke every session. Done as a bulk DELETE rather than
    # loading the rows, since a user with many devices shouldn't turn one
    # reset into a long transaction.
    await db.execute(delete(Session).where(Session.user_id == user.id))

    await db.commit()
    await db.refresh(user)
    return user

