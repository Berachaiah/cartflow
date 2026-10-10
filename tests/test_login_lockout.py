"""
Integration tests for failed-login lockout (app/services/session.py:login()).

Covers the four behaviours the lockout must guarantee:
  - a run of wrong passwords ending in the right one succeeds AND clears the
    counter (an honest fat-fingering user isn't punished);
  - MAX_FAILED_LOGINS consecutive wrong passwords locks the account, and the
    lock refuses even the CORRECT password;
  - the lock is SILENT — it returns the same generic 401 as a wrong password,
    never a distinguishable 429 (05 sec 20: generic message, no enumeration);
  - the lock lifts once locked_until passes, and a success then resets state.

Exercised through the real ASGI app. Where a test needs to fast-forward past
the 15-minute lock, it rewrites locked_until directly via the `db` session
(both fixtures share one in-memory engine), since the suite can't sleep.
"""

from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services.session import MAX_FAILED_LOGINS

_PASSWORD = "password123"
_WRONG = "definitely-not-it"


async def _signup(client: AsyncClient, *, username: str, email: str) -> None:
    r = await client.post(
        "/api/auth/signup",
        json={
            "role": "individual",
            "full_name": f"{username} test",
            "username": username,
            "email": email,
            "password": _PASSWORD,
        },
    )
    assert r.status_code == 201, r.text


async def _login(client: AsyncClient, identifier: str, password: str):
    return await client.post(
        "/api/auth/login", json={"identifier": identifier, "password": password}
    )


async def _get_user(db: AsyncSession, username: str) -> User:
    return (
        await db.execute(sa.select(User).where(User.username_normalized == username))
    ).scalar_one()


async def test_wrong_then_correct_succeeds_and_resets_counter(db, client: AsyncClient):
    """Below the threshold, a correct password still works — and wipes the
    accumulated failure count so honest mistakes leave no residue."""
    await _signup(client, username="fatfinger", email="fatfinger@example.com")

    # One shy of the lockout threshold, all wrong.
    for _ in range(MAX_FAILED_LOGINS - 1):
        r = await _login(client, "fatfinger", _WRONG)
        assert r.status_code == 401

    # The correct password now succeeds (not locked yet).
    r = await _login(client, "fatfinger", _PASSWORD)
    assert r.status_code == 200, r.text

    # ...and the counter/lock are cleared.
    user = await _get_user(db, "fatfinger")
    assert user.failed_login_attempts == 0
    assert user.locked_until is None


async def test_threshold_locks_and_rejects_correct_password(db, client: AsyncClient):
    """MAX_FAILED_LOGINS wrong attempts lock the account; the correct password
    is then refused too — with the SAME generic 401, never a distinct status."""
    await _signup(client, username="brutee", email="brutee@example.com")

    for _ in range(MAX_FAILED_LOGINS):
        r = await _login(client, "brutee", _WRONG)
        assert r.status_code == 401

    # locked_until is stamped in the future.
    user = await _get_user(db, "brutee")
    assert user.failed_login_attempts >= MAX_FAILED_LOGINS
    assert user.locked_until is not None

    # The correct password is refused while locked — and the reply is
    # indistinguishable from a wrong-password 401 (no enumeration oracle).
    r = await _login(client, "brutee", _PASSWORD)
    assert r.status_code == 401


async def test_lock_expires_then_correct_password_works(db, client: AsyncClient):
    """Once locked_until passes, the correct password logs in again and resets
    the failure state."""
    await _signup(client, username="waiter", email="waiter@example.com")

    for _ in range(MAX_FAILED_LOGINS):
        assert (await _login(client, "waiter", _WRONG)).status_code == 401

    # Fast-forward past the lock instead of sleeping LOCKOUT_DURATION.
    user = await _get_user(db, "waiter")
    assert user.locked_until is not None
    user.locked_until = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db.commit()

    r = await _login(client, "waiter", _PASSWORD)
    assert r.status_code == 200, r.text

    await db.refresh(user)
    assert user.failed_login_attempts == 0
    assert user.locked_until is None


async def test_post_expiry_single_wrong_guess_relocks(db, client: AsyncClient):
    """After the lock lifts, one more wrong guess re-locks immediately — a
    patient attacker gets a single attempt per window, not a fresh batch of
    MAX_FAILED_LOGINS."""
    await _signup(client, username="patient", email="patient@example.com")

    for _ in range(MAX_FAILED_LOGINS):
        assert (await _login(client, "patient", _WRONG)).status_code == 401

    user = await _get_user(db, "patient")
    user.locked_until = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db.commit()

    # A single wrong guess after expiry.
    assert (await _login(client, "patient", _WRONG)).status_code == 401

    await db.refresh(user)
    # Re-locked on that one guess, and the correct password is refused again.
    assert user.locked_until is not None
    assert (await _login(client, "patient", _PASSWORD)).status_code == 401


async def test_unknown_identifier_never_errors_or_locks(client: AsyncClient):
    """A login for an identifier that matches no account fails generically and
    never blows up — there's no row to lock, and it must be indistinguishable
    from a real account's wrong-password path."""
    for _ in range(MAX_FAILED_LOGINS + 2):
        r = await _login(client, "ghost-user", _WRONG)
        assert r.status_code == 401
