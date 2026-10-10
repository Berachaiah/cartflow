"""
Shared FastAPI dependencies. Currently: current-user resolution from the
session cookie (Depends(get_current_user) in any protected route).
"""

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import UnauthorizedError
from app.database.session import get_db
from app.models.user import User
from app.services.session import get_current_user_from_token

settings = get_settings()


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    raw_token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not raw_token:
        raise UnauthorizedError("Authentication is required.")
    return await get_current_user_from_token(db, raw_token)


async def get_current_user_optional(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Non-strict counterpart to get_current_user for SERVER-RENDERED PAGES.

    A page must render for signed-out visitors too, so a missing/expired/revoked
    session resolves to None (a signed-out state) rather than raising a 401. The
    happy path is identical to get_current_user — same cookie, same token
    validation via get_current_user_from_token — only the two failure modes are
    swallowed:
      - no cookie at all → None (never logged in / logged out);
      - a cookie that fails validation → None (expired, revoked, or the user was
        suspended/deleted) — get_current_user_from_token raises UnauthorizedError
        for all of these, which we catch.
    Do NOT use this to guard an action; use get_current_user there so the 401
    still fires. This is purely for deciding what identity to show in the chrome.
    """
    raw_token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not raw_token:
        return None
    try:
        return await get_current_user_from_token(db, raw_token)
    except UnauthorizedError:
        return None
