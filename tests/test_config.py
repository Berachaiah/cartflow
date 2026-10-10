"""
Settings-validation tests — specifically the production guard on
APP_SECRET_KEY (app/core/config.py).

The key signs session cookies AND the Google finish-signup token (which stands
in for a password), so a placeholder/short key in production is an auth bypass.
The guard must fire in production and stay inert everywhere else.

Settings is constructed directly with explicit kwargs so these don't depend on
the local .env; pydantic-settings still honours passed values over env.
"""

import pytest

from app.core.config import Settings

_STRONG = "x" * 40


def test_production_rejects_default_secret():
    with pytest.raises(ValueError):
        Settings(APP_ENV="production", APP_SECRET_KEY="change-me-in-env")


def test_production_rejects_short_secret():
    with pytest.raises(ValueError):
        Settings(APP_ENV="production", APP_SECRET_KEY="tooshort")


def test_production_accepts_strong_secret():
    s = Settings(APP_ENV="production", APP_SECRET_KEY=_STRONG)
    assert s.is_production is True


def test_development_tolerates_default_secret():
    # Dev/test convenience: a weak key is fine when not in production.
    s = Settings(APP_ENV="development", APP_SECRET_KEY="change-me-in-env")
    assert s.is_production is False


def test_staging_tolerates_default_secret():
    # Only 'production' is guarded; staging is intentionally not.
    s = Settings(APP_ENV="staging", APP_SECRET_KEY="change-me-in-env")
    assert s.is_production is False
