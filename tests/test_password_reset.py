"""
Password-reset flow tests.

These lean on the security properties enumerated in
app/services/password_reset.py's module docstring — each one gets a test
that would fail loudly if the property regressed, because every one of
them is the kind of bug that is invisible in manual QA (a reset that
"works" can still be leaking account existence or leaving old sessions
alive).

Emails are intercepted rather than sent: `sent_emails` patches the
`send_email` symbol *as imported into the reset service*, not in
smtp_client. Patching the origin module would miss it — `from ... import
send_email` binds a reference at import time, so rebinding the source
afterwards has no effect on the already-bound name.
"""

import re
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.security import hash_password, verify_password
from app.models.session import Session
from app.models.user import AccountStatus, AccountType, User
from app.models.verification_token import (
    MAX_OTP_ATTEMPTS,
    TokenPurpose,
    VerificationToken,
)

pytestmark = pytest.mark.asyncio

PASSWORD = "or1ginal-passw0rd"
NEW_PASSWORD = "br4nd-new-passw0rd"


@pytest.fixture
def sent_emails(monkeypatch):
    """Capture outbound email instead of hitting SMTP."""
    box: list[dict] = []

    async def _capture(*, to: str, subject: str, html: str) -> str:
        box.append({"to": to, "subject": subject, "html": html})
        return "test-message-id"

    monkeypatch.setattr("app.services.password_reset.send_email", _capture)
    return box


@pytest_asyncio.fixture
async def user(db) -> User:
    u = User(
        id=uuid.uuid4(),
        account_type=AccountType.STUDENT,
        account_status=AccountStatus.ACTIVE,
        email="ada@example.com",
        password_hash=hash_password(PASSWORD),
        username="Berachaiah",
        username_normalized="berachaiah",
        display_name="Ada Lovelace",
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


def extract_otp(html: str) -> str:
    """Pull the 6-digit code out of the rendered email."""
    match = re.search(r">(\d{6})</span>", html)
    assert match, "no 6-digit OTP found in email body"
    return match.group(1)


def extract_token(html: str) -> str:
    match = re.search(r"/reset-password\?token=([A-Za-z0-9_\-]+)", html)
    assert match, "no reset link found in email body"
    return match.group(1)


# --- property 1: no account enumeration ------------------------------


async def test_unknown_identifier_returns_same_message_and_sends_nothing(
    db, user, sent_emails
):
    from app.services.password_reset import GENERIC_RESET_RESPONSE, request_password_reset

    known = await request_password_reset(db, "ada@example.com")
    unknown = await request_password_reset(db, "nobody@example.com")

    # Identical response bodies are the whole point — the endpoint must not
    # work as a "does this account exist?" oracle.
    assert known == unknown == GENERIC_RESET_RESPONSE
    assert [m["to"] for m in sent_emails] == ["ada@example.com"]


async def test_lookup_accepts_username_as_well_as_email(db, user, sent_emails):
    from app.services.password_reset import request_password_reset

    await request_password_reset(db, "Berachaiah")
    assert len(sent_emails) == 1

    # Case-insensitive, matching login's identifier handling.
    sent_emails.clear()
    await db.execute(
        VerificationToken.__table__.delete()
    )
    await db.commit()
    await request_password_reset(db, "BERACHAIAH")
    assert len(sent_emails) == 1


async def test_suspended_account_cannot_reset(db, user, sent_emails):
    from app.services.password_reset import GENERIC_RESET_RESPONSE, request_password_reset

    user.account_status = AccountStatus.SUSPENDED
    await db.commit()

    # Same generic message, but no email: a reset must not be a way around
    # a suspension.
    assert await request_password_reset(db, "ada@example.com") == GENERIC_RESET_RESPONSE
    assert sent_emails == []


# --- both credentials are delivered together -------------------------


async def test_request_emails_both_a_link_and_a_code(db, user, sent_emails):
    from app.services.password_reset import request_password_reset

    await request_password_reset(db, "ada@example.com")
    html = sent_emails[0]["html"]

    assert extract_token(html)
    assert extract_otp(html)

    # One row backs both, so redeeming either burns the other.
    rows = (await db.execute(select(VerificationToken))).scalars().all()
    assert len(rows) == 1
    assert rows[0].otp_hash is not None


# --- property 2: hashes only -----------------------------------------


async def test_raw_token_and_otp_are_never_persisted(db, user, sent_emails):
    from app.services.password_reset import request_password_reset

    await request_password_reset(db, "ada@example.com")
    html = sent_emails[0]["html"]
    raw_token, raw_otp = extract_token(html), extract_otp(html)

    row = (await db.execute(select(VerificationToken))).scalar_one()
    assert row.token_hash != raw_token
    assert row.otp_hash != raw_otp
    assert len(row.token_hash) == 64 and len(row.otp_hash) == 64


# --- reset via link ---------------------------------------------------


async def test_reset_via_link_changes_password(db, user, sent_emails):
    from app.services.password_reset import request_password_reset, reset_password

    await request_password_reset(db, "ada@example.com")
    token = extract_token(sent_emails[0]["html"])

    await reset_password(db, new_password=NEW_PASSWORD, token=token)

    await db.refresh(user)
    assert verify_password(NEW_PASSWORD, user.password_hash)
    assert not verify_password(PASSWORD, user.password_hash)


# --- reset via OTP ----------------------------------------------------


async def test_reset_via_otp_changes_password(db, user, sent_emails):
    from app.services.password_reset import request_password_reset, reset_password

    await request_password_reset(db, "ada@example.com")
    otp = extract_otp(sent_emails[0]["html"])

    await reset_password(
        db, new_password=NEW_PASSWORD, identifier="ada@example.com", otp_code=otp
    )

    await db.refresh(user)
    assert verify_password(NEW_PASSWORD, user.password_hash)


# --- property 3: single use, shared fate ------------------------------


async def test_link_cannot_be_reused(db, user, sent_emails):
    from app.core.exceptions import ValidationAppError
    from app.services.password_reset import request_password_reset, reset_password

    await request_password_reset(db, "ada@example.com")
    token = extract_token(sent_emails[0]["html"])

    await reset_password(db, new_password=NEW_PASSWORD, token=token)

    with pytest.raises(ValidationAppError):
        await reset_password(db, new_password="third-passw0rd!", token=token)


async def test_using_the_link_also_burns_the_otp(db, user, sent_emails):
    """The two credentials share one row, so spending one spends both.

    If this fails, a reset link used by its owner would leave a live OTP
    sitting in an inbox that could later reset the account again.
    """
    from app.core.exceptions import ValidationAppError
    from app.services.password_reset import request_password_reset, reset_password

    await request_password_reset(db, "ada@example.com")
    html = sent_emails[0]["html"]
    token, otp = extract_token(html), extract_otp(html)

    await reset_password(db, new_password=NEW_PASSWORD, token=token)

    with pytest.raises(ValidationAppError):
        await reset_password(
            db, new_password="third-passw0rd!", identifier="ada@example.com", otp_code=otp
        )


# --- property 4: OTP brute-force cap ----------------------------------


async def test_otp_locks_after_max_attempts(db, user, sent_emails):
    from app.core.exceptions import ValidationAppError
    from app.services.password_reset import request_password_reset, verify_reset_credential

    await request_password_reset(db, "ada@example.com")
    real_otp = extract_otp(sent_emails[0]["html"])
    wrong = "000000" if real_otp != "000000" else "111111"

    for _ in range(MAX_OTP_ATTEMPTS):
        with pytest.raises(ValidationAppError):
            await verify_reset_credential(
                db, identifier="ada@example.com", otp_code=wrong
            )

    # The cap must hold even once the CORRECT code is supplied — otherwise
    # it only slows an attacker down rather than stopping them.
    with pytest.raises(ValidationAppError):
        await verify_reset_credential(
            db, identifier="ada@example.com", otp_code=real_otp
        )


async def test_correct_otp_does_not_burn_an_attempt(db, user, sent_emails):
    from app.services.password_reset import request_password_reset, verify_reset_credential

    await request_password_reset(db, "ada@example.com")
    otp = extract_otp(sent_emails[0]["html"])

    await verify_reset_credential(db, identifier="ada@example.com", otp_code=otp)

    row = (await db.execute(select(VerificationToken))).scalar_one()
    assert row.otp_attempts == 0
    # Verification must not consume the token, or the user would have to
    # type the code a second time on the new-password screen.
    assert row.used_at is None


async def test_otp_is_scoped_to_its_own_account(db, user, sent_emails):
    """An OTP must not unlock a different user who happens to share digits.

    Guards against a global "find any token with this otp_hash" lookup,
    which would let an attacker reset a stranger's password by guessing
    six digits with no knowledge of who they belong to.
    """
    from app.core.exceptions import ValidationAppError
    from app.services.password_reset import request_password_reset, verify_reset_credential

    other = User(
        id=uuid.uuid4(),
        account_type=AccountType.STUDENT,
        account_status=AccountStatus.ACTIVE,
        email="grace@example.com",
        password_hash=hash_password(PASSWORD),
        username="grace",
        username_normalized="grace",
        display_name="Grace Hopper",
    )
    db.add(other)
    await db.commit()

    await request_password_reset(db, "ada@example.com")
    ada_otp = extract_otp(sent_emails[0]["html"])

    sent_emails.clear()
    await request_password_reset(db, "grace@example.com")

    with pytest.raises(ValidationAppError):
        await verify_reset_credential(
            db, identifier="grace@example.com", otp_code=ada_otp
        )


# --- property 5: sessions die on reset --------------------------------


async def test_reset_revokes_every_existing_session(db, user, sent_emails):
    """Whoever knew the old password must lose access immediately.

    This is usually the actual reason someone resets, so a reset that
    leaves sessions alive fails at its main job.
    """
    from app.services.password_reset import request_password_reset, reset_password

    now = datetime.now(timezone.utc)
    for _ in range(3):
        db.add(
            Session(
                user_id=user.id,
                session_token_hash=uuid.uuid4().hex + uuid.uuid4().hex,
                created_at=now,
                last_activity=now,
                expires_at=now + timedelta(days=14),
            )
        )
    await db.commit()

    await request_password_reset(db, "ada@example.com")
    await reset_password(
        db, new_password=NEW_PASSWORD, token=extract_token(sent_emails[0]["html"])
    )

    remaining = (
        await db.execute(select(Session).where(Session.user_id == user.id))
    ).scalars().all()
    assert remaining == []


# --- expiry -----------------------------------------------------------


async def test_expired_credential_is_rejected(db, user, sent_emails):
    from app.core.exceptions import ValidationAppError
    from app.services.password_reset import request_password_reset, reset_password

    await request_password_reset(db, "ada@example.com")
    html = sent_emails[0]["html"]

    row = (await db.execute(select(VerificationToken))).scalar_one()
    row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db.commit()

    with pytest.raises(ValidationAppError):
        await reset_password(db, new_password=NEW_PASSWORD, token=extract_token(html))

    with pytest.raises(ValidationAppError):
        await reset_password(
            db,
            new_password=NEW_PASSWORD,
            identifier="ada@example.com",
            otp_code=extract_otp(html),
        )


# --- property 7: re-request supersedes --------------------------------


async def test_new_request_invalidates_the_previous_one(db, user, sent_emails, monkeypatch):
    """There must never be two live codes for one account."""
    import app.services.password_reset as pr
    from app.core.exceptions import ValidationAppError

    monkeypatch.setattr(pr, "RESEND_COOLDOWN", timedelta(seconds=0))

    await pr.request_password_reset(db, "ada@example.com")
    first_token = extract_token(sent_emails[0]["html"])

    await pr.request_password_reset(db, "ada@example.com")
    second_token = extract_token(sent_emails[1]["html"])

    assert first_token != second_token
    rows = (await db.execute(select(VerificationToken))).scalars().all()
    assert len(rows) == 1

    with pytest.raises(ValidationAppError):
        await pr.reset_password(db, new_password=NEW_PASSWORD, token=first_token)

    await pr.reset_password(db, new_password=NEW_PASSWORD, token=second_token)


async def test_rapid_rerequest_is_silently_suppressed(db, user, sent_emails):
    """The cooldown must NOT surface as a distinguishable error.

    Raising a 429 here would hand back the enumeration oracle the generic
    response exists to close: POST twice for any identifier, and only a
    real account answers differently the second time. So the second call
    returns the same message and simply doesn't send.
    """
    from app.services.password_reset import GENERIC_RESET_RESPONSE, request_password_reset

    first = await request_password_reset(db, "ada@example.com")
    second = await request_password_reset(db, "ada@example.com")

    assert first == second == GENERIC_RESET_RESPONSE
    assert len(sent_emails) == 1


async def test_cooldown_is_indistinguishable_over_http(client, db, user, sent_emails):
    """The oracle test proper: a real account and a fake one must produce
    byte-identical replies across repeated requests."""
    real = [
        await client.post("/api/auth/forgot-password", json={"identifier": "ada@example.com"})
        for _ in range(2)
    ]
    fake = [
        await client.post("/api/auth/forgot-password", json={"identifier": "ghost@example.com"})
        for _ in range(2)
    ]

    assert [r.status_code for r in real] == [200, 200]
    assert [r.status_code for r in fake] == [200, 200]
    assert {r.json()["message"] for r in real + fake} == {
        r.json()["message"] for r in real
    }
    assert len(sent_emails) == 1  # only the real account, only once


async def test_rerequest_after_the_cooldown_sends_again(db, user, sent_emails):
    from sqlalchemy import select as sa_select

    from app.services.password_reset import RESEND_COOLDOWN, request_password_reset

    await request_password_reset(db, "ada@example.com")

    row = (await db.execute(sa_select(VerificationToken))).scalar_one()
    row.created_at = datetime.now(timezone.utc) - RESEND_COOLDOWN - timedelta(seconds=5)
    await db.commit()

    await request_password_reset(db, "ada@example.com")
    assert len(sent_emails) == 2


# --- password quality -------------------------------------------------


async def test_cannot_reset_to_the_current_password(db, user, sent_emails):
    """Often the user is resetting *because* the old password leaked."""
    from app.core.exceptions import ValidationAppError
    from app.services.password_reset import request_password_reset, reset_password

    await request_password_reset(db, "ada@example.com")
    token = extract_token(sent_emails[0]["html"])

    with pytest.raises(ValidationAppError):
        await reset_password(db, new_password=PASSWORD, token=token)


# --- HTTP surface -----------------------------------------------------


async def test_forgot_password_endpoint_is_enumeration_safe(client, db, user, sent_emails):
    known = await client.post(
        "/api/auth/forgot-password", json={"identifier": "ada@example.com"}
    )
    unknown = await client.post(
        "/api/auth/forgot-password", json={"identifier": "ghost@example.com"}
    )

    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json()


async def test_reset_endpoint_rejects_mismatched_confirmation(client, user):
    r = await client.post(
        "/api/auth/reset-password",
        json={
            "token": "x" * 32,
            "new_password": NEW_PASSWORD,
            "confirm_password": "something-else-entirely",
        },
    )
    assert r.status_code == 422


async def test_reset_endpoint_rejects_sending_both_paths(client, user):
    """Accepting both at once would let an attacker pair a valid token with
    a guessed OTP and probe the code space at no cost."""
    r = await client.post(
        "/api/auth/reset-password",
        json={
            "token": "x" * 32,
            "identifier": "ada@example.com",
            "otp_code": "123456",
            "new_password": NEW_PASSWORD,
            "confirm_password": NEW_PASSWORD,
        },
    )
    assert r.status_code == 422


async def test_login_works_with_the_new_password_after_reset(
    client, db, user, sent_emails
):
    """The end-to-end contract the user actually cares about."""
    from app.services.password_reset import request_password_reset, reset_password

    await request_password_reset(db, "ada@example.com")
    await reset_password(
        db, new_password=NEW_PASSWORD, token=extract_token(sent_emails[0]["html"])
    )

    stale = await client.post(
        "/api/auth/login", json={"identifier": "Berachaiah", "password": PASSWORD}
    )
    assert stale.status_code == 401

    fresh = await client.post(
        "/api/auth/login", json={"identifier": "Berachaiah", "password": NEW_PASSWORD}
    )
    assert fresh.status_code == 200


# --- username availability -------------------------------------------


async def test_username_availability(client, db, user):
    taken = await client.get("/api/auth/check-username", params={"username": "Berachaiah"})
    assert taken.json()["available"] is False

    # Case-insensitive: usernames are unique on the normalized column.
    assert (
        await client.get("/api/auth/check-username", params={"username": "BERACHAIAH"})
    ).json()["available"] is False

    free = await client.get("/api/auth/check-username", params={"username": "Chinaza"})
    assert free.json()["available"] is True
    assert free.json()["reason"] is None


async def test_pure_alphabet_username_is_valid(client):
    """Explicitly guards the rule the user asked about: a plain name with
    no digits, dots, or underscores is a legal username."""
    for name in ("Berachaiah", "Ada", "chinaza"):
        r = await client.get("/api/auth/check-username", params={"username": name})
        assert r.json()["available"] is True, name
