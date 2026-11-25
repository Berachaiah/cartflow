"""
Firebase ID-token verification — the browser half of "Continue with Google".

WHY THIS EXISTS. The app already had a server-side Google OAuth redirect
(`services/google_oauth.py`), and that flow still works. But the product's web
client is set up with Firebase, and Firebase sign-in happens in the page: the SDK
opens a popup, Google authenticates, and the page is left holding a signed ID
token. The server's only job is to decide whether that token is genuine — which
is what this module does, and nothing else.

HOW THE TOKEN IS CHECKED. A Firebase ID token is an RS256 JWT signed by Google.
So verification is local and needs no shared secret:

  * signature — checked against Google's published signing keys (fetched once
    per process and cached by `PyJWKClient`, keyed by the token's `kid`);
  * `aud` — must be our own project id, or a token minted for another app would
    be accepted here;
  * `iss` — must be `https://securetoken.google.com/<project>` for the same
    reason;
  * `exp` / `iat` / `sub` — required claims, so an unsigned or expired token
    cannot pass by omission.

WHY THE GOOGLE SUBJECT, NOT THE FIREBASE UID. Accounts are keyed by
`users.google_sub` — the Google account's own `sub` — because that is what the
redirect flow stores. The Firebase UID is a different identifier for the same
person, so reading `firebase.identities["google.com"][0]` keeps one Google
account mapping to one CartFlow account no matter which front door the user
came through. A token without that claim falls back to `sub` only so a
non-Google provider is not silently mis-keyed; accounts created that way are
still unique per provider account.

FAILURES ARE 401s, NOT 500s. A token that fails any check is a rejected sign-in,
so every PyJWT failure is turned into `UnauthorizedError` with one message —
never the library's text, which names keys and algorithms.
"""

from __future__ import annotations

import logging
from functools import lru_cache

import jwt
from jwt import PyJWKClient

from app.core.config import get_settings
from app.core.exceptions import ConflictError, UnauthorizedError

logger = logging.getLogger("cartflow.firebase_auth")

# Google's rotating public keys for Firebase ID tokens. A constant, not config:
# it is Google's endpoint, not one of ours.
_JWKS_URL = (
    "https://www.googleapis.com/service_accounts/v1/jwk/"
    "securetoken@system.gserviceaccount.com"
)

_REJECTED = "Google sign-in could not be verified. Please try again."


@lru_cache(maxsize=1)
def _key_client() -> PyJWKClient:
    """One key client per process: it caches the fetched keys and re-fetches
    only when an unknown `kid` appears, which is how Google rotates them."""
    return PyJWKClient(_JWKS_URL, cache_keys=True)


def verify_id_token(id_token: str) -> dict:
    """Return the verified identity, or raise.

    The dict is the same shape `google_oauth.exchange_and_identify()` returns
    (`sub`, `email`, `email_verified`, `name`), so the sign-in endpoint can hand
    either flow's identity to the same code path.
    """
    settings = get_settings()
    if not settings.firebase_enabled:
        raise ConflictError("Google sign-in is not enabled.")

    try:
        signing_key = _key_client().get_signing_key_from_jwt(id_token).key
        claims = jwt.decode(
            id_token,
            signing_key,
            algorithms=["RS256"],
            audience=settings.FIREBASE_PROJECT_ID,
            issuer=f"https://securetoken.google.com/{settings.FIREBASE_PROJECT_ID}",
            options={"require": ["exp", "iat", "aud", "iss", "sub"]},
        )
    except jwt.PyJWTError as exc:
        # Deliberately logged by class name only: the message can contain token
        # fragments, and this is not the place to keep them.
        logger.warning("firebase id token rejected: %s", type(exc).__name__)
        raise UnauthorizedError(_REJECTED) from exc
    except Exception as exc:  # network failure fetching keys, malformed token
        logger.warning("firebase id token unverifiable: %s", type(exc).__name__)
        raise UnauthorizedError(_REJECTED) from exc

    identities = (claims.get("firebase") or {}).get("identities") or {}
    google_ids = identities.get("google.com") or []
    email = claims.get("email")
    if not email:
        # A provider that does not assert an email cannot create an account here:
        # `users.email` is the login identifier and must not be guessed.
        logger.warning("firebase token had no email claim")
        raise UnauthorizedError("Google did not share an email address for that account.")

    return {
        "sub": google_ids[0] if google_ids else claims["sub"],
        "email": email,
        "email_verified": bool(claims.get("email_verified")),
        "name": claims.get("name") or "",
    }
