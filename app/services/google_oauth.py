"""
Google OAuth 2.0 (OpenID Connect) — authorize-URL construction and the
code→identity exchange.

Deliberately hand-rolled on httpx + itsdangerous rather than pulling in an
OAuth library: the flow is two HTTP calls and a signed state string, both
already available (no new dependency), and the surface stays small and
auditable.

Flow (see app/routers/auth.py for the wiring):
  1. build_authorize_url(intent) → redirect the browser to Google. `intent`
     (login | signup) is round-tripped in a SIGNED, TIMED `state` param — it
     both prevents CSRF (the callback verifies our signature) and tells the
     callback which page the user came from.
  2. Google redirects back to google_redirect_uri with ?code&state.
  3. verify_state(state, expected_nonce) → the original intent (raises on
     tamper/expiry, or when the nonce doesn't match the browser's cookie).
  4. exchange_and_identify(code) → {sub, email, name, email_verified}.

Secrets (client secret, APP_SECRET_KEY) never leave the server — nothing here
is exposed to templates or browser JS.
"""

import logging
import secrets

import httpx
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.core.config import get_settings
from app.core.exceptions import UnauthorizedError, ValidationAppError
from app.core.security import constant_time_compare

logger = logging.getLogger("cartflow.google_oauth")

settings = get_settings()

# OIDC endpoints. Constants, not config — these are Google's, not ours.
_GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
_GOOGLE_USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"

_SCOPES = "openid email profile"

# Namespaces for the two signed payloads this app mints, so a token minted for
# one purpose can never be replayed as the other (both use APP_SECRET_KEY).
_STATE_SALT = "google-oauth-state"
_FINISH_SIGNUP_SALT = "google-finish-signup"

# The OAuth `state` is a short round-trip (consent takes seconds-to-minutes).
_STATE_MAX_AGE_SECONDS = 15 * 60
# The finish-signup token bridges callback → the /signup form submit; give the
# user time to fill it in, but keep it short — it stands in for a password.
_FINISH_SIGNUP_MAX_AGE_SECONDS = 30 * 60


def _serializer(salt: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.APP_SECRET_KEY, salt=salt)


def build_authorize_url(intent: str) -> tuple[str, str]:
    """Build the Google consent URL to redirect the user to, plus the raw state
    nonce the caller must store in a short-lived cookie.

    `intent` ('login' | 'signup') is carried in the signed state and echoed back
    to the callback. A random `nonce` is ALSO embedded in the state and returned
    separately so the router can drop it in a cookie: the callback then requires
    the state's nonce to match the cookie, binding the flow to the browser that
    started it (defeats login-CSRF — a signed state alone only proves the server
    minted it, not that this browser requested it)."""
    nonce = secrets.token_urlsafe(32)
    state = _serializer(_STATE_SALT).dumps({"intent": intent, "nonce": nonce})
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": _SCOPES,
        "state": state,
        # Ask for a fresh account chooser so a shared browser doesn't silently
        # reuse the last Google session.
        "prompt": "select_account",
    }
    return f"{_GOOGLE_AUTH_ENDPOINT}?{httpx.QueryParams(params)}", nonce


def verify_state(state: str, expected_nonce: str | None) -> str:
    """Validate the signed state from the callback and return the intent.

    `expected_nonce` is the value the browser presents from its state cookie.
    Raises UnauthorizedError on a missing/tampered/expired state, or when the
    nonce doesn't match the cookie (a likely CSRF attempt, a cross-browser
    redirect, or a lost cookie)."""
    try:
        data = _serializer(_STATE_SALT).loads(state, max_age=_STATE_MAX_AGE_SECONDS)
    except SignatureExpired:
        raise UnauthorizedError("This Google sign-in link has expired. Please try again.")
    except BadSignature:
        raise UnauthorizedError("Invalid Google sign-in state.")

    nonce = data.get("nonce")
    if not expected_nonce or not nonce or not constant_time_compare(nonce, expected_nonce):
        raise UnauthorizedError("Invalid Google sign-in state.")

    intent = data.get("intent")
    return intent if intent in ("login", "signup") else "login"


async def exchange_and_identify(code: str) -> dict:
    """Exchange the authorization code for tokens, then fetch the user's
    profile. Returns {sub, email, name, email_verified}. Raises
    UnauthorizedError if Google rejects the code, omits an email, or reports
    the email as unverified."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        token_resp = await client.post(
            _GOOGLE_TOKEN_ENDPOINT,
            data={
                "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": settings.google_redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        if token_resp.status_code != 200:
            logger.warning("Google token exchange failed: %s", token_resp.text)
            raise UnauthorizedError("Google sign-in failed. Please try again.")

        access_token = token_resp.json().get("access_token")
        if not access_token:
            raise UnauthorizedError("Google sign-in failed. Please try again.")

        userinfo_resp = await client.get(
            _GOOGLE_USERINFO_ENDPOINT,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if userinfo_resp.status_code != 200:
            logger.warning("Google userinfo fetch failed: %s", userinfo_resp.text)
            raise UnauthorizedError("Google sign-in failed. Please try again.")

    info = userinfo_resp.json()
    sub = info.get("sub")
    email = info.get("email")
    if not sub or not email:
        raise UnauthorizedError("Google didn't return an email for this account.")

    # Only ever act on a Google-VERIFIED email. Downstream this address is used
    # to (a) link this Google identity onto an existing CartFlow account matched
    # by email, and (b) create a new account pre-verified. Both trust that the
    # address genuinely belongs to whoever consented — an assertion only the
    # `email_verified` claim backs. Consumer @gmail.com is always verified, but
    # a Workspace/custom-domain account can emit email_verified=false and would
    # otherwise let someone bind to (or pre-verify) an address they don't own.
    if not bool(info.get("email_verified", False)):
        logger.warning("Google returned an unverified email for sub=%s", sub)
        raise UnauthorizedError(
            "Your Google account's email isn't verified. Verify it with Google, "
            "then try again."
        )

    return {
        "sub": sub,
        "email": email.lower(),
        "name": info.get("name") or email.split("@")[0],
        "email_verified": True,
    }


def issue_finish_signup_token(identity: dict) -> str:
    """Mint the short-lived signed token handed to the finish-signup page for a
    NEW Google user. Carries the verified identity so the /signup submit can
    create the account without re-contacting Google (and without a password)."""
    return _serializer(_FINISH_SIGNUP_SALT).dumps(
        {"sub": identity["sub"], "email": identity["email"], "name": identity["name"]}
    )


def verify_finish_signup_token(token: str) -> dict:
    """Validate a finish-signup token at /signup submit time and return the
    identity {sub, email, name}. Raises ValidationAppError on tamper/expiry so
    the form shows a field-level error and the user restarts Google sign-in."""
    try:
        return _serializer(_FINISH_SIGNUP_SALT).loads(
            token, max_age=_FINISH_SIGNUP_MAX_AGE_SECONDS
        )
    except SignatureExpired:
        raise ValidationAppError(
            "Your Google sign-in session expired. Please start again.",
            fields={"google_token": "Expired — restart Google sign-in."},
        )
    except BadSignature:
        raise ValidationAppError(
            "Invalid Google sign-in session. Please start again.",
            fields={"google_token": "Invalid — restart Google sign-in."},
        )
