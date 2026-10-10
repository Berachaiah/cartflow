"""
Application configuration.

Single source of truth for environment-driven settings. Values are read
from environment variables (or a local .env file in development) and
validated once at startup via `get_settings()`.

Reference: docs/engineering PRD Chapter 12, section 44 "Environment
Configuration" — this list of variables mirrors that section directly.

Rules (per PRD):
- Never commit production secrets.
- Use separate dev / staging / production values.
- Do not expose server secrets to Jinja templates or browser JavaScript.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# The placeholder shipped as the default. Never acceptable in production — it
# signs session data AND the Google finish-signup token (which stands in for a
# password), so a known key lets anyone forge either.
_DEFAULT_SECRET_KEY = "change-me-in-env"
# Floor for a real key. 32+ random chars is the usual minimum for HMAC/signing
# secrets; short keys weaken every itsdangerous signature the app mints.
_MIN_SECRET_KEY_LENGTH = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    # --- Core app ---------------------------------------------------
    APP_NAME: str = "CartFlow"
    APP_ENV: Literal["development", "staging", "production"] = "development"
    APP_SECRET_KEY: str = "change-me-in-env"  # used for session signing (itsdangerous)
    DEBUG: bool = True

    # Base URL used to build clickable links in transactional emails
    # (verification, password reset). No trailing slash.
    APP_BASE_URL: str = "http://127.0.0.1:8000"

    # --- Database -----------------------------------------------------
    # e.g. postgresql+asyncpg://user:pass@host:5432/cartflow
    DATABASE_URL: str = "postgresql+asyncpg://localhost:5432/cartflow_dev"
    DB_ECHO: bool = False
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10

    # --- Redis (optional for V1, see PRD Ch.12 sec 25) ------------------
    REDIS_URL: str | None = None

    # --- Media (Cloudinary) --------------------------------------------
    CLOUDINARY_CLOUD_NAME: str | None = None
    CLOUDINARY_API_KEY: str | None = None
    CLOUDINARY_API_SECRET: str | None = None
    # Top-level folder every upload is filed under, e.g. "cartflow" →
    # cartflow/avatars/<id>. A Cloudinary folder is not a resource you connect
    # to and has no credentials of its own — it is purely a path prefix on the
    # upload call, and Cloudinary creates it on first use if it doesn't exist.
    # Set this to the folder name you made in the Cloudinary console.
    CLOUDINARY_FOLDER: str = "cartflow"

    # --- Payments --------------------------------------------------------
    PAYMENT_PROVIDER: Literal["anchor", "paystack"] = "paystack"
    ANCHOR_API_KEY: str | None = None
    PAYSTACK_SECRET_KEY: str | None = None

    # --- Email (Resend) -----------------------------------------------
    RESEND_API_KEY: str | None = None

    # --- SMTP (Hacom mailbox — replaces Resend) ---------------------------
    SMTP_HOST: str = "mail.supremecluster.com"
    SMTP_PORT: int = 465
    SMTP_USERNAME: str = "notifications@cartflow.appotg.com"
    SMTP_PASSWORD: str = ""
    SMTP_USE_SSL: bool = True
    EMAIL_FROM: str = "no-reply@cartflow.africa"
    EMAIL_REPLY_TO: str | None = None
    # Where user reports (§23) are delivered. Left unset it falls back to
    # EMAIL_FROM via `reports_email` below, so reporting works out of the box
    # and a report is never dropped for want of configuration — the mail simply
    # lands in the same mailbox everything else comes from until someone points
    # this at a real moderation address.
    REPORTS_EMAIL: str | None = None

    # --- Social login (Google) ------------------------------------------
    # The auth pages render the "Continue with Google" button only when a
    # client ID is configured. That keeps a non-functional button out of the
    # UI until the OAuth callback actually exists (milestone 2) instead of
    # shipping a dead control users can click.
    GOOGLE_CLIENT_ID: str | None = None
    GOOGLE_CLIENT_SECRET: str | None = None
    # Where Google redirects back after consent. Must EXACTLY match one of the
    # "Authorized redirect URIs" registered in the Google Cloud console. Left
    # unset in .env, it derives from APP_BASE_URL (see google_redirect_uri) so
    # dev works with no extra config; set it explicitly in production.
    GOOGLE_REDIRECT_URI: str | None = None

    # --- Observability ----------------------------------------------
    SENTRY_DSN: str | None = None

    # --- Networking / CORS --------------------------------------------
    ALLOWED_HOSTS: str = "*"
    CORS_ORIGINS: str = ""

    # --- Sessions -------------------------------------------------------
    SESSION_COOKIE_NAME: str = "cartflow_session"
    SESSION_MAX_AGE_SECONDS: int = 60 * 60 * 24 * 14  # 14 days


    @model_validator(mode="after")
    def _require_strong_secret_in_production(self) -> "Settings":
        """Refuse to boot production with the placeholder or a too-short
        APP_SECRET_KEY.

        Development and tests are unaffected — they run with APP_ENV other than
        'production', where a weak key is tolerated for convenience. In
        production the key signs session cookies and the Google finish-signup
        token (which creates a passwordless, pre-verified account), so a known
        or guessable key is a full authentication bypass. Failing loudly at
        startup beats shipping a forgeable signer.
        """
        if self.APP_ENV != "production":
            return self
        if self.APP_SECRET_KEY == _DEFAULT_SECRET_KEY:
            raise ValueError(
                "APP_SECRET_KEY is still the default placeholder. Set a unique, "
                "random secret (32+ chars) in the production environment."
            )
        if len(self.APP_SECRET_KEY) < _MIN_SECRET_KEY_LENGTH:
            raise ValueError(
                f"APP_SECRET_KEY must be at least {_MIN_SECRET_KEY_LENGTH} "
                "characters in production."
            )
        return self

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    @property
    def google_oauth_enabled(self) -> bool:
        """Google sign-in is offered only when BOTH credentials are set. Gates
        the button in templates and the OAuth routes — a half-configured
        install shows no dead button and returns 404 rather than erroring."""
        return bool(self.GOOGLE_CLIENT_ID and self.GOOGLE_CLIENT_SECRET)

    @property
    def google_redirect_uri(self) -> str:
        """The registered callback URL. Uses GOOGLE_REDIRECT_URI verbatim when
        set, else derives it from APP_BASE_URL so local dev needs no extra
        config. Whatever this resolves to MUST be registered in Google Cloud."""
        if self.GOOGLE_REDIRECT_URI:
            return self.GOOGLE_REDIRECT_URI
        return f"{self.APP_BASE_URL.rstrip('/')}/api/auth/google/callback"

    @property
    def reports_email(self) -> str:
        """Where a user report is emailed. REPORTS_EMAIL when set, else
        EMAIL_FROM — same shape as `google_redirect_uri`, and for the same
        reason: a feature should not need extra configuration to work at all."""
        return self.REPORTS_EMAIL or self.EMAIL_FROM

    @property
    def media_enabled(self) -> bool:
        """Image uploads are offered only when all three Cloudinary credentials
        are set. Same shape as `google_oauth_enabled`, and for the same reason:
        with no credentials the upload endpoint returns 503 and the UI renders an
        honest "not configured yet" state instead of a control that fails on tap.

        The folder is deliberately NOT part of this check — it has a default and
        is just a path prefix, so a missing one can't break an upload."""
        return bool(
            self.CLOUDINARY_CLOUD_NAME
            and self.CLOUDINARY_API_KEY
            and self.CLOUDINARY_API_SECRET
        )

    @property
    def allowed_hosts_list(self) -> list[str]:
        return [h.strip() for h in self.ALLOWED_HOSTS.split(",") if h.strip()]

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor — import and call this, don't instantiate Settings() directly."""
    return Settings()
