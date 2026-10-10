"""
Email-verification flow tests.

Two behaviors here are easy to get wrong in ways manual QA never catches,
so both get explicit coverage:

  - The resend cooldown compares a stored timestamp against `now`. Under
    SQLite the stored value comes back naive, so an unguarded subtraction
    raises TypeError instead of enforcing the cooldown.
  - A spent token means two different things depending on whether the
    account actually ended up verified. Clicking the same link twice must
    succeed; clicking a link that a newer send replaced must not silently
    report success.

Email is intercepted by patching `send_email` *as imported into
email_verification*, not in smtp_client — `from ... import send_email`
binds at import time, so patching the origin module would miss it.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.exceptions import ConflictError, NotFoundError, RateLimitedError, ValidationAppError
from app.core.security import hash_password, hash_token
from app.models.user import AccountStatus, AccountType, User
from app.models.verification_token import TokenPurpose, VerificationToken
from app.services.email_verification import (
    RESEND_COOLDOWN,
    request_verification_resend,
    send_verification_email,
    verify_email_token,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture
def sent_emails(monkeypatch):
    box: list[dict] = []

    async def _capture(*, to: str, subject: str, html: str) -> str:
        box.append({"to": to, "subject": subject, "html": html})
        return "test-message-id"

    monkeypatch.setattr("app.services.email_verification.send_email", _capture)
    return box


@pytest_asyncio.fixture
async def user(db) -> User:
    u = User(
        id=uuid.uuid4(),
        account_type=AccountType.STUDENT,
        account_status=AccountStatus.ACTIVE,
        email="ada@example.com",
        password_hash=hash_password("or1ginal-passw0rd"),
        username="Berachaiah",
        username_normalized="berachaiah",
        display_name="Ada Lovelace",
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


def _token_from_email(html: str) -> str:
    """Pull the raw token out of the emailed link — the only place it
    exists, since the DB stores nothing but its hash."""
    marker = "/verify-email?token="
    start = html.index(marker) + len(marker)
    end = start
    while end < len(html) and html[end] not in "\"'&< \n":
        end += 1
    return html[start:end]


async def _issue(db, user) -> None:
    await send_verification_email(db, user)
    await db.commit()


# --- sending ----------------------------------------------------------


async def test_verification_email_carries_a_working_link(db, user, sent_emails):
    await _issue(db, user)

    assert len(sent_emails) == 1
    assert sent_emails[0]["to"] == user.email

    raw = _token_from_email(sent_emails[0]["html"])
    assert len(raw) > 20

    # Only the hash is persisted; the raw token must not appear anywhere.
    rows = (await db.execute(select(VerificationToken))).scalars().all()
    assert len(rows) == 1
    assert rows[0].token_hash == hash_token(raw)
    assert raw not in rows[0].token_hash


async def test_new_send_invalidates_the_previous_link(db, user, sent_emails):
    await _issue(db, user)
    first = _token_from_email(sent_emails[0]["html"])

    await _issue(db, user)
    second = _token_from_email(sent_emails[1]["html"])
    assert first != second

    # The superseded link must not verify, and must say so rather than
    # claiming the address is already done.
    with pytest.raises(ValidationAppError) as exc:
        await verify_email_token(db, first)
    assert "most recent email" in str(exc.value)

    verified = await verify_email_token(db, second)
    await db.commit()
    assert verified.email_verified_at is not None


# --- verifying --------------------------------------------------------


async def test_verify_marks_the_account_and_burns_the_token(db, user, sent_emails):
    await _issue(db, user)
    raw = _token_from_email(sent_emails[0]["html"])

    result = await verify_email_token(db, raw)
    await db.commit()

    assert result.id == user.id
    assert result.email_verified_at is not None

    row = (await db.execute(select(VerificationToken))).scalar_one()
    assert row.used_at is not None


async def test_clicking_the_same_link_twice_still_succeeds(db, user, sent_emails):
    """Double-clicks and mail-client prefetches are the norm, not the
    exception. The second call is a no-op, not an error."""
    await _issue(db, user)
    raw = _token_from_email(sent_emails[0]["html"])

    first = await verify_email_token(db, raw)
    await db.commit()
    stamped_at = first.email_verified_at

    again = await verify_email_token(db, raw)
    await db.commit()

    assert again.id == user.id
    # Idempotent: the original verification time is not overwritten.
    assert again.email_verified_at == stamped_at


async def test_expired_link_is_rejected(db, user, sent_emails):
    await _issue(db, user)
    raw = _token_from_email(sent_emails[0]["html"])

    row = (await db.execute(select(VerificationToken))).scalar_one()
    row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db.commit()

    with pytest.raises(ValidationAppError) as exc:
        await verify_email_token(db, raw)
    assert "expired" in str(exc.value).lower()

    await db.refresh(user)
    assert user.email_verified_at is None


async def test_unknown_token_is_rejected(db, user, sent_emails):
    with pytest.raises(NotFoundError):
        await verify_email_token(db, "not-a-real-token-value")


async def test_a_password_reset_token_cannot_verify_an_email(db, user):
    """Purpose is part of the lookup. A reset token is emailed to the same
    address, so without the purpose filter it would double as a
    verification link."""
    raw = "reset-token-not-for-verification"
    db.add(
        VerificationToken(
            user_id=user.id,
            purpose=TokenPurpose.PASSWORD_RESET,
            token_hash=hash_token(raw),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        )
    )
    await db.commit()

    with pytest.raises(NotFoundError):
        await verify_email_token(db, raw)


# --- resend -----------------------------------------------------------


async def test_resend_within_the_cooldown_is_rate_limited(db, user, sent_emails):
    """Regression guard: this path subtracts a stored timestamp from an
    aware `now`. Before ensure_utc() it raised TypeError under SQLite —
    the cooldown never ran, and the caller got a 500."""
    await _issue(db, user)

    with pytest.raises(RateLimitedError) as exc:
        await request_verification_resend(db, user)

    assert "wait" in str(exc.value).lower()
    assert len(sent_emails) == 1  # nothing extra went out


async def test_resend_after_the_cooldown_sends_again(db, user, sent_emails):
    await _issue(db, user)

    row = (await db.execute(select(VerificationToken))).scalar_one()
    row.created_at = datetime.now(timezone.utc) - RESEND_COOLDOWN - timedelta(seconds=5)
    await db.commit()

    await request_verification_resend(db, user)
    await db.commit()

    assert len(sent_emails) == 2


async def test_resend_is_refused_once_verified(db, user, sent_emails):
    await _issue(db, user)
    raw = _token_from_email(sent_emails[0]["html"])
    await verify_email_token(db, raw)
    await db.commit()

    with pytest.raises(ConflictError):
        await request_verification_resend(db, user)


# --- HTTP surface -----------------------------------------------------


async def test_resend_endpoint_does_not_leak_account_existence(client, sent_emails):
    res = await client.post(
        "/api/auth/resend-verification", json={"email": "nobody@example.com"}
    )
    assert res.status_code == 200
    assert "If that email is registered" in res.json()["message"]
    assert sent_emails == []


async def test_resend_matches_email_case_insensitively(client, db, user, sent_emails):
    """Signup stores the address lowercased. A resend typed as
    "Ada@Example.com" must still find the account — before the .lower()
    in the router it silently returned the generic message and never
    sent anything.

    The cooldown is stepped past first, since the service-level cooldown
    would otherwise suppress the send and hide the thing being tested.
    """
    await _issue(db, user)

    row = (await db.execute(select(VerificationToken))).scalar_one()
    row.created_at = datetime.now(timezone.utc) - RESEND_COOLDOWN - timedelta(seconds=5)
    await db.commit()

    res = await client.post(
        "/api/auth/resend-verification", json={"email": "ADA@EXAMPLE.COM"}
    )
    assert res.status_code == 200
    assert len(sent_emails) == 2  # the original plus the resend


async def test_resend_cooldown_is_indistinguishable_over_http(client, db, user, sent_emails):
    """A registered address inside its cooldown must answer exactly like an
    unregistered one — otherwise repeated POSTs enumerate accounts."""
    await _issue(db, user)

    hit = await client.post("/api/auth/resend-verification", json={"email": user.email})
    miss = await client.post(
        "/api/auth/resend-verification", json={"email": "ghost@example.com"}
    )

    assert hit.status_code == miss.status_code == 200
    assert hit.json() == miss.json()
    assert len(sent_emails) == 1  # the cooldown suppressed the resend


async def test_resend_for_an_already_verified_address_is_silent(client, db, user, sent_emails):
    """Once verified, a resend must not confirm the address is registered —
    the response is identical to an unknown address. No exception leaks."""
    await _issue(db, user)
    raw = _token_from_email(sent_emails[0]["html"])
    await verify_email_token(db, raw)
    await db.commit()

    res = await client.post(
        "/api/auth/resend-verification", json={"email": user.email}
    )
    assert res.status_code == 200
    assert "If that email is registered" in res.json()["message"]
    assert len(sent_emails) == 1  # nothing new went out


async def test_verify_endpoint_round_trip(client, db, user, sent_emails):
    await _issue(db, user)
    raw = _token_from_email(sent_emails[0]["html"])

    res = await client.post("/api/auth/verify-email", json={"token": raw})
    assert res.status_code == 200
    assert "verified" in res.json()["message"].lower()

    # Second click over HTTP is a success too, not a 4xx.
    again = await client.post("/api/auth/verify-email", json={"token": raw})
    assert again.status_code == 200


async def test_verify_endpoint_rejects_a_bad_token(client):
    res = await client.post("/api/auth/verify-email", json={"token": "0123456789abc"})
    assert res.status_code in (400, 404, 422)
