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
    # TLS for the Postgres connection. The production target is Supabase, whose
    # pooler is reached across the public internet with the password in the URL,
    # so "require" is the default: a misconfigured or downgraded connection
    # should fail loudly rather than quietly send credentials in the clear.
    # Set DB_SSL=disable for a local Postgres with no TLS of its own. Ignored for
    # SQLite, which has no transport to encrypt.
    #
    # "require" encrypts but does NOT verify the certificate, so it stops passive
    # snooping and not an active man-in-the-middle. "verify-full" is the mode that
    # checks both, and it needs DB_SSL_CA_FILE because Supabase's pooler
    # certificate chains to "Supabase Root 2021 CA" — a private CA the system
    # trust store has never heard of (measured: verify against the system store
    # fails with "self-signed certificate in certificate chain").
    DB_SSL: Literal["require", "verify-ca", "verify-full", "prefer", "allow", "disable"] = "require"
    # Path to Supabase's root certificate (prod-ca-2021.crt), used only when
    # DB_SSL is verify-ca or verify-full. Required in those modes: verification
    # against a CA nobody configured is not verification. Supabase rotates this
    # certificate rarely but does rotate it, so treat the file as configuration
    # and re-download it from Dashboard -> Database settings if TLS starts failing.
    DB_SSL_CA_FILE: str | None = None

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
    # Which gateway the Shop offers by default. Flutterwave and Squad are both
    # wired (the Shop lets the buyer pick per checkout); Anchor and Paystack are
    # named but not implemented, so they are never offered.
    PAYMENT_PROVIDER: Literal["anchor", "paystack", "flutterwave", "squad"] = "flutterwave"
    ANCHOR_API_KEY: str | None = None
    PAYSTACK_SECRET_KEY: str | None = None

    # Flutterwave (https://developer.flutterwave.com). Three keys, three jobs:
    #
    #   FLUTTERWAVE_SECRET_KEY    server-only. Creates the payment link and verifies
    #                             a transaction. Never reaches a template, a log line
    #                             or the browser.
    #   FLUTTERWAVE_PUBLIC_KEY    safe in the browser; used by Flutterwave's inline
    #                             checkout and by support to identify the account.
    #   FLUTTERWAVE_ENCRYPTION_KEY only used by the direct-card API. The hosted
    #                             checkout in app/services/flutterwave.py does not read
    #                             it; it lives here so a rotation is one place.
    #
    # FLUTTERWAVE_WEBHOOK_HASH is the "Secret hash" set in Dashboard → Webhooks. A
    # webhook call carries no signature of its own — Flutterwave echoes this value
    # back in the `verif-hash` header, and that header is the ONLY thing that makes
    # the POST trustworthy. Unset means webhooks are refused (401), never accepted.
    FLUTTERWAVE_PUBLIC_KEY: str | None = None
    FLUTTERWAVE_SECRET_KEY: str | None = None
    FLUTTERWAVE_ENCRYPTION_KEY: str | None = None
    FLUTTERWAVE_WEBHOOK_HASH: str | None = None
    FLUTTERWAVE_CURRENCY: str = "NGN"
    FLUTTERWAVE_API_BASE: str = "https://api.flutterwave.com/v3"

    # Squad (https://docs.squadco.com). The second gateway, offered beside
    # Flutterwave so a failed card on one is not a dead end on the other.
    #
    #   SQUAD_SECRET_KEY  server-only: initiates a transaction and verifies one.
    #   SQUAD_PUBLIC_KEY  identifies the merchant; not used by the server-side
    #                     checkout this app performs, kept for the inline widget.
    #
    # Two differences from Flutterwave that the service module handles and callers
    # should not have to remember:
    #   * amount is in KOBO on the wire, while every price here is whole naira;
    #   * a webhook is authenticated by an HMAC of the raw body keyed with the
    #     SECRET key (header `x-squad-encrypted-body`), not by a shared header
    #     value. There is no separate hash to configure.
    SQUAD_PUBLIC_KEY: str | None = None
    SQUAD_SECRET_KEY: str | None = None
    SQUAD_CURRENCY: str = "NGN"
    SQUAD_API_BASE: str = "https://sandbox-api-d.squadco.com"

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
    def flutterwave_enabled(self) -> bool:
        """Checkout is offered only when the SECRET key exists, because the secret
        is the only one that can create a payment link or verify one. Same shape as
        `google_oauth_enabled`: with no credentials the Shop's checkout button
        refuses with a clear message instead of a redirect into a 502."""
        return bool(self.FLUTTERWAVE_SECRET_KEY)

    @property
    def squad_enabled(self) -> bool:
        """Same rule as Flutterwave: no secret key, no checkout. A half-configured
        gateway must not appear as a button that 502s on tap."""
        return bool(self.SQUAD_SECRET_KEY)

    @property
    def enabled_payment_providers(self) -> list[dict]:
        """The gateways the Shop may offer, in display order.

        Returned as data rather than booleans so the checkout markup and the
        checkout endpoint cannot disagree about which providers exist: the same
        list builds the picker and validates the posted `provider`.
        """
        providers: list[dict] = []
        if self.flutterwave_enabled:
            providers.append({"key": "flutterwave", "label": "Flutterwave"})
        if self.squad_enabled:
            providers.append({"key": "squad", "label": "Squad"})
        return providers

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
