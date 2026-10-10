"""
Security primitives: password hashing and opaque session-token generation.

Per PRD Chapter 12, section 7 (Authentication), CartFlow's primary web app
uses secure HTTP-only session cookies rather than client-stored JWTs.
Password hashing uses Argon2id.

This module intentionally stays low-level and stateless — session
persistence (a sessions table, rotation, revocation) belongs in the
Auth domain's service layer, not here.
"""

import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError

_password_hasher = PasswordHasher()


def hash_password(plain_password: str) -> str:
    """Hash a plaintext password using Argon2id."""
    return _password_hasher.hash(plain_password)


def verify_password(plain_password: str, password_hash: str | None) -> bool:
    """Verify a plaintext password against a stored Argon2id hash.

    Returns False on any mismatch or malformed-hash error rather than
    raising, so callers can treat this as a simple boolean check. A None
    hash (a passwordless Google-only account) always fails here — such an
    account has no local password to match and must authenticate via Google.
    """
    if not password_hash:
        return False
    try:
        return _password_hasher.verify(password_hash, plain_password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """True if the stored hash was created with outdated Argon2 parameters."""
    return _password_hasher.check_needs_rehash(password_hash)


def generate_session_token(n_bytes: int = 32) -> str:
    """Generate a cryptographically secure, URL-safe opaque session token.

    Store only a hash of this token server-side (see PRD Ch.12 sec 17 —
    "store a hash of the scan token" applies to session tokens too); the
    raw value goes in the HttpOnly cookie.
    """
    return secrets.token_urlsafe(n_bytes)


def generate_csrf_token(n_bytes: int = 32) -> str:
    """Generate a CSRF token for the double-submit-cookie pattern."""
    return secrets.token_urlsafe(n_bytes)


def generate_otp(digits: int = 6) -> str:
    """Generate a numeric one-time code, zero-padded to `digits`.

    Uses secrets.randbelow, not random — this guards a password reset, so
    a predictable PRNG would be a real vulnerability. Zero-padding matters:
    formatting an int would silently turn 0042 into "42" and hand out a
    shorter, weaker code.
    """
    upper = 10**digits
    return str(secrets.randbelow(upper)).zfill(digits)


def hash_token(raw: str) -> str:
    """SHA-256 hex digest of a raw token or OTP.

    Deliberately a plain hash and not Argon2: these values are
    high-entropy and short-lived, so the slow-KDF stretching that
    passwords need buys nothing here, and password reset would inherit a
    per-verification CPU cost. The 6-digit OTP is low-entropy but is
    protected by an attempt cap and a short TTL instead
    (see verification_token.MAX_OTP_ATTEMPTS).
    """
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def constant_time_compare(a: str, b: str) -> bool:
    """Timing-safe string comparison (use for CSRF token / token-hash checks)."""
    return secrets.compare_digest(a, b)
