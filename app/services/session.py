"""
Session/login service.

Per PRD 05-authentication-and-onboarding.md sec 12-13, 19-21 and the
architectural decision: HttpOnly cookie + server-side session record
(V1), JWT deferred to V2 for mobile/public-API clients.

Failed-login lockout (05 sec 20, 03 sec 24) IS implemented here: login()
counts consecutive wrong passwords per account and, once MAX_FAILED_LOGINS is
reached, stamps users.locked_until so further attempts are refused for
LOCKOUT_DURATION — even the correct password. The refusal is the SAME generic
"invalid username or password" as a wrong guess, never a distinguishable 429:
05 sec 20 requires "a generic error message to prevent account enumeration",
and a "your account is locked" reply would let an attacker learn an address is
registered simply by tripping the lock (a nonexistent account never locks).
This mirrors the reset-OTP cap's silent-cooldown reasoning in password_reset.py
(property 8). The counter increment is committed BEFORE raising — otherwise the
request transaction (get_db) rolls back on the exception and the cap could
never advance.

Deliberately NOT yet implemented (flagged, not silently skipped):
  - Per-IP / global request rate limiting (05 sec 19). That belongs at the
    edge (reverse proxy / Redis token bucket), not per-row in the DB; the
    per-account lockout above is the application-layer half of the story.
  - CSRF (double-submit cookie) — core.security already has the
    primitives (generate_csrf_token, constant_time_compare); wiring it
    in is the next piece once basic login/logout is confirmed working.

Account-status gating: PENDING_VERIFICATION users CAN log in — V1 does
not require email verification before platform use (05 sec 15, explicit).
Only SUSPENDED and DELETED block login (03 sec 20: "Suspended users
cannot log in").
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import UnauthorizedError
from app.core.security import generate_session_token, verify_password
from app.models.session import Session
from app.models.user import AccountStatus, User
from app.repositories.session import SessionRepository, hash_session_token

settings = get_settings()

BLOCKED_LOGIN_STATUSES = {AccountStatus.SUSPENDED, AccountStatus.DELETED}

# Failed-login lockout (05 sec 20, 03 sec 24). The threshold mirrors the
# reset-OTP cap (MAX_OTP_ATTEMPTS = 5). 15 minutes is long enough to make
# automated credential-stuffing uneconomical, short enough that the flip side —
# someone who knows a username deliberately locking its owner out — is a brief
# nuisance rather than a lasting lockout (admins can also clear it; 05 sec 20).
MAX_FAILED_LOGINS = 5
LOCKOUT_DURATION = timedelta(minutes=15)


def _aware(value: datetime) -> datetime:
    """Force a UTC tzinfo onto a DB datetime.

    SQLite returns naive datetimes even from a DateTime(timezone=True) column,
    so comparing a stored locked_until against now(timezone.utc) would raise
    TypeError under tests while working fine on Postgres. Mirrors the same
    helper in password_reset.py — kept local rather than shared to avoid a
    service→service import for a one-line utility.
    """
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)



async def create_session(
    db: AsyncSession,
    user: User,
    *,
    ip_address: str | None,
    user_agent: str | None,
) -> str:
    """Mint a server-side Session row for an ALREADY-AUTHENTICATED user and
    return the raw token to set as the cookie. Shared by password login and the
    Google OAuth callback — the Google user has no local password, so callers
    that authenticate by other means still get sessions the same way.

    Also stamps last_login_at. Does NOT check credentials or account status —
    that's the caller's job (login() does the password + status checks; the
    Google callback trusts Google's identity and checks status itself)."""
    raw_token = generate_session_token()
    now = datetime.now(timezone.utc)

    session = Session(
        user_id=user.id,
        session_token_hash=hash_session_token(raw_token),
        ip_address=ip_address,
        user_agent=user_agent,
        created_at=now,
        last_activity=now,
        expires_at=now + timedelta(seconds=settings.SESSION_MAX_AGE_SECONDS),
    )
    db.add(session)
    await db.flush()

    user.last_login_at = now
    return raw_token


async def login(
    db: AsyncSession,
    *,
    identifier: str,
    password: str,
    ip_address: str | None,
    user_agent: str | None,
) -> tuple[User, str]:
    """Returns (user, raw_session_token). Raises UnauthorizedError on any
    failure — deliberately the same generic message for 'no such user'
    and 'wrong password', per 05 sec 21 (never reveal which one it was).

    `identifier` is a username OR an email. Both columns are matched in one
    query rather than branching on "does it contain an @": an email is not a
    legal username (`@` fails USERNAME_PATTERN), so the two namespaces can't
    collide and a single OR is both correct and one round-trip.
    """
    normalized = identifier.strip().lower()

    stmt = select(User).where(
        or_(User.email == normalized, func.lower(User.username) == normalized),
        User.deleted_at.is_(None),
    )
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    # No such user: fail generically WITHOUT touching any counter. There is no
    # row to lock, and a nonexistent account must behave identically to a real
    # one under the same generic message (05 sec 20) so this can't be used to
    # tell registered addresses apart from unregistered ones.
    if user is None:
        raise UnauthorizedError("Invalid username or password.")

    now = datetime.now(timezone.utc)

    # Locked? Refuse before spending a hash verify. The reply is the SAME
    # generic failure as a wrong password — announcing the lock would confirm
    # the account exists (see module docstring). A correct password during the
    # lock window is refused too: that is the whole point of a lockout.
    if user.locked_until is not None and _aware(user.locked_until) > now:
        raise UnauthorizedError("Invalid username or password.")

    # A passwordless (Google-only) account has password_hash=NULL; verify_password
    # returns False for it, so it can't be logged into here — it must use Google.
    if not verify_password(password, user.password_hash):
        # Count this failure and, at the threshold, lock the account. Committed
        # NOW because raising below unwinds the request transaction (get_db
        # rolls back on any exception), which would otherwise discard the
        # increment and leave the cap unreachable. Same pattern as the
        # reset-OTP cap (password_reset.py).
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= MAX_FAILED_LOGINS:
            user.locked_until = now + LOCKOUT_DURATION
        await db.commit()
        raise UnauthorizedError("Invalid username or password.")

    if user.account_status in BLOCKED_LOGIN_STATUSES:
        raise UnauthorizedError("Invalid username or password.")

    # Correct password on an unlocked, permitted account: clear the failure
    # state so a run of wrong guesses followed by the right one doesn't leave a
    # primed counter (or a stale lock) behind for the next login.
    if user.failed_login_attempts or user.locked_until is not None:
        user.failed_login_attempts = 0
        user.locked_until = None

    raw_token = await create_session(
        db, user, ip_address=ip_address, user_agent=user_agent
    )
    return user, raw_token


async def logout(db: AsyncSession, raw_token: str) -> None:
    """Revokes the session matching this token. Silently no-ops if the
    token doesn't match anything — logout should never error just
    because the cookie was already stale."""
    session_repo = SessionRepository(db)
    session = await session_repo.get_by_raw_token(raw_token)
    if session is not None and session.revoked_at is None:
        session.revoked_at = datetime.now(timezone.utc)


async def get_current_user_from_token(db: AsyncSession, raw_token: str) -> User:
    """Validates a raw session token from the cookie, updates
    last_activity, and returns the associated user. Raises
    UnauthorizedError for any invalid/expired/revoked session."""
    session_repo = SessionRepository(db)
    session = await session_repo.get_by_raw_token(raw_token)

    if session is None or not session.is_active:
        raise UnauthorizedError("Your session has expired. Please log in again.")

    stmt = select(User).where(User.id == session.user_id, User.deleted_at.is_(None))
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if user is None or user.account_status in BLOCKED_LOGIN_STATUSES:
        raise UnauthorizedError("Your session has expired. Please log in again.")

    session.last_activity = datetime.now(timezone.utc)

    return user
