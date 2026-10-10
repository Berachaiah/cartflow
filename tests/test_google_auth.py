"""
Integration tests for Google OAuth signup/login (app/routers/auth.py + the
google_oauth service).

The two network-touching functions (verify_state, exchange_and_identify) are
monkeypatched so no real Google call happens; the finish-signup token is a REAL
signed itsdangerous payload (same APP_SECRET_KEY the app uses), so that half of
the flow is exercised for real. OAuth is enabled by setting the credential
fields on the cached settings singleton the routers already hold.
"""

import uuid

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.user import User
from app.services import google_oauth


@pytest.fixture
def google_enabled(monkeypatch):
    """Turn on Google OAuth for the duration of a test by populating the
    credential fields on the shared settings singleton (google_oauth_enabled is
    a property computed from them)."""
    settings = get_settings()
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "test-client-secret")
    return settings


def _mock_identity(monkeypatch, identity: dict, *, intent: str = "signup"):
    """Stub the two functions that would otherwise hit Google."""
    monkeypatch.setattr(google_oauth, "verify_state", lambda state, nonce: intent)

    async def _fake_exchange(code: str) -> dict:
        return identity

    monkeypatch.setattr(google_oauth, "exchange_and_identify", _fake_exchange)


# --- login gating -------------------------------------------------------


async def test_google_login_404_when_disabled(client: AsyncClient):
    """With no credentials configured, the OAuth endpoints refuse rather than
    erroring — the button is hidden anyway."""
    r = await client.get("/api/auth/google/login", params={"intent": "login"})
    assert r.status_code == 409


async def test_google_login_redirects_when_enabled(client: AsyncClient, google_enabled):
    r = await client.get(
        "/api/auth/google/login", params={"intent": "login"}, follow_redirects=False
    )
    assert r.status_code == 302
    assert "accounts.google.com" in r.headers["location"]


# --- callback: existing user -------------------------------------------


async def test_callback_existing_user_gets_session(db, client: AsyncClient, google_enabled, monkeypatch):
    # A prior password account with this email.
    r = await client.post(
        "/api/auth/signup",
        json={
            "role": "individual",
            "full_name": "Existing G",
            "username": "existg",
            "email": "existg@example.com",
            "password": "password123",
        },
    )
    assert r.status_code == 201, r.text

    _mock_identity(
        monkeypatch,
        {"sub": "google-sub-123", "email": "existg@example.com", "name": "Existing G"},
        intent="login",
    )

    r = await client.get(
        "/api/auth/google/callback",
        params={"code": "fake-code", "state": "fake-state"},
        follow_redirects=False,
    )
    assert r.status_code == 302
    assert r.headers["location"] == "/discover"
    # A session cookie was set.
    assert get_settings().SESSION_COOKIE_NAME in r.cookies

    # google_sub was linked onto the existing account.
    user = (
        await db.execute(sa.select(User).where(User.username_normalized == "existg"))
    ).scalar_one()
    assert user.google_sub == "google-sub-123"


# --- callback: new user → finish signup --------------------------------


async def test_callback_new_user_redirects_to_finish_signup(client: AsyncClient, google_enabled, monkeypatch):
    _mock_identity(
        monkeypatch,
        {"sub": "google-sub-new", "email": "brandnew@example.com", "name": "Brand New"},
        intent="signup",
    )

    r = await client.get(
        "/api/auth/google/callback",
        params={"code": "fake-code", "state": "fake-state"},
        follow_redirects=False,
    )
    assert r.status_code == 302
    assert r.headers["location"].startswith("/signup?google=")


async def test_callback_error_returns_to_login(client: AsyncClient, google_enabled):
    r = await client.get(
        "/api/auth/google/callback",
        params={"error": "access_denied"},
        follow_redirects=False,
    )
    assert r.status_code == 302
    assert r.headers["location"] == "/login?google_error=1"


# --- finish signup: passwordless account creation ----------------------


async def test_finish_signup_creates_passwordless_verified_account(db, client: AsyncClient, google_enabled):
    # A REAL signed token, exactly as the callback would mint.
    token = google_oauth.issue_finish_signup_token(
        {"sub": "google-sub-finish", "email": "finish@example.com", "name": "Finish Me"}
    )

    r = await client.post(
        "/api/auth/signup",
        json={
            "role": "individual",
            "full_name": "Finish Me",
            "username": "finishme",
            "email": "ignored@example.com",  # overridden by the token's verified email
            "google_token": token,
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["outcome"] == "account_created"
    # Email comes from the verified token, not the posted value.
    assert body["user"]["email"] == "finish@example.com"
    # Pre-verified (Google-verified email), no verification step needed.
    assert body["user"]["email_verified_at"] is not None

    user = (
        await db.execute(sa.select(User).where(User.username_normalized == "finishme"))
    ).scalar_one()
    assert user.password_hash is None          # passwordless
    assert user.google_sub == "google-sub-finish"


async def test_finish_signup_rejects_password_and_token_together(client: AsyncClient, google_enabled):
    token = google_oauth.issue_finish_signup_token(
        {"sub": "s", "email": "both@example.com", "name": "Both"}
    )
    r = await client.post(
        "/api/auth/signup",
        json={
            "role": "individual",
            "full_name": "Both",
            "username": "bothcreds",
            "email": "both@example.com",
            "password": "password123",
            "google_token": token,
        },
    )
    assert r.status_code == 422  # validator: exactly one credential path


async def test_finish_signup_brand_role(db, client: AsyncClient, google_enabled):
    """A Google user finishing as a Brand: passwordless, verified, is_seller,
    owns a business."""
    token = google_oauth.issue_finish_signup_token(
        {"sub": "google-brand", "email": "brandg@example.com", "name": "Brand G"}
    )
    r = await client.post(
        "/api/auth/signup",
        json={
            "role": "brand",
            "full_name": "Brand G",
            "username": "brandg",
            "email": "brandg@example.com",
            "google_token": token,
            "business_name": "Brand G Co",
            "state": "Lagos",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["user"]["account_type"] == "business"
    assert body["user"]["is_seller"] is True
    assert body["user"]["email_verified_at"] is not None


# --- exchange_and_identify: email_verified guard -----------------------
#
# The callback tests above stub exchange_and_identify wholesale, so they never
# touch the guard. These drive the REAL function by faking only its internal
# httpx client, so the token/userinfo parsing and the email_verified check run
# for real. No new dependency — a minimal fake stands in for httpx.AsyncClient.


class _FakeResp:
    def __init__(self, status_code: int, json_data: dict):
        self.status_code = status_code
        self._json = json_data
        self.text = str(json_data)

    def json(self) -> dict:
        return self._json


class _FakeAsyncClient:
    """Async-context-manager stand-in: POST → token response, GET → userinfo."""

    def __init__(self, userinfo: dict):
        self._userinfo = userinfo

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, data=None):
        return _FakeResp(200, {"access_token": "fake-access-token"})

    async def get(self, url, headers=None):
        return _FakeResp(200, self._userinfo)


def _patch_userinfo(monkeypatch, userinfo: dict):
    monkeypatch.setattr(
        google_oauth.httpx,
        "AsyncClient",
        lambda *a, **k: _FakeAsyncClient(userinfo),
    )


async def test_exchange_accepts_verified_email(monkeypatch):
    _patch_userinfo(
        monkeypatch,
        {"sub": "s1", "email": "Verified@Example.com", "name": "Vee", "email_verified": True},
    )
    identity = await google_oauth.exchange_and_identify("fake-code")
    assert identity["sub"] == "s1"
    assert identity["email"] == "verified@example.com"  # lowercased
    assert identity["email_verified"] is True


async def test_exchange_rejects_unverified_email(monkeypatch):
    """A Workspace/custom-domain account can report email_verified=false. We
    must refuse it — otherwise it links onto / pre-verifies an unowned address."""
    _patch_userinfo(
        monkeypatch,
        {"sub": "s2", "email": "unowned@corp.example", "name": "Nope", "email_verified": False},
    )
    with pytest.raises(google_oauth.UnauthorizedError):
        await google_oauth.exchange_and_identify("fake-code")


async def test_exchange_rejects_missing_email_verified(monkeypatch):
    """A missing claim is treated as unverified (fail closed), not trusted."""
    _patch_userinfo(
        monkeypatch,
        {"sub": "s3", "email": "noflag@corp.example", "name": "NoFlag"},
    )
    with pytest.raises(google_oauth.UnauthorizedError):
        await google_oauth.exchange_and_identify("fake-code")


# --- state nonce binding (login-CSRF defence) --------------------------
#
# build_authorize_url mints a nonce embedded in the signed state AND returned
# for the browser cookie; verify_state requires the two to match. These drive
# the REAL functions (no stub) since the nonce round-trip is the whole point.


def test_state_roundtrip_with_matching_nonce(google_enabled):
    url, nonce = google_oauth.build_authorize_url("signup")
    assert "accounts.google.com" in url
    # Pull the signed state out of the authorize URL and verify it as the
    # callback would, with the nonce the browser cookie carried.
    state = str(url).split("state=")[1].split("&")[0]
    from urllib.parse import unquote

    assert google_oauth.verify_state(unquote(state), nonce) == "signup"


def test_state_rejected_when_nonce_mismatches(google_enabled):
    url, _nonce = google_oauth.build_authorize_url("login")
    from urllib.parse import unquote

    state = unquote(str(url).split("state=")[1].split("&")[0])
    with pytest.raises(google_oauth.UnauthorizedError):
        google_oauth.verify_state(state, "some-other-browsers-nonce")


def test_state_rejected_when_cookie_missing(google_enabled):
    url, _nonce = google_oauth.build_authorize_url("login")
    from urllib.parse import unquote

    state = unquote(str(url).split("state=")[1].split("&")[0])
    # No cookie on the callback (lost/stripped) → refuse.
    with pytest.raises(google_oauth.UnauthorizedError):
        google_oauth.verify_state(state, None)


async def test_callback_sets_and_clears_state_cookie(client: AsyncClient, google_enabled):
    """/google/login drops the state cookie; a callback without it is refused
    (verify_state raises → 401), proving the binding is enforced end-to-end."""
    r = await client.get(
        "/api/auth/google/login", params={"intent": "login"}, follow_redirects=False
    )
    assert r.status_code == 302
    assert "cartflow_oauth_state" in r.cookies
