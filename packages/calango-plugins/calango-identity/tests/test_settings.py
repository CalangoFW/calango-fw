from __future__ import annotations

import os

import pytest
from calango_identity.settings import IdentitySettings
from pydantic import ValidationError


def test_settings_requires_private_key():
    """IdentitySettings raises ValidationError if PRIVATE_KEY is missing."""
    with pytest.raises(ValidationError):
        IdentitySettings(PUBLIC_KEY="some-key")  # ty: ignore[missing-argument]  # intentional


def test_settings_requires_public_key():
    """IdentitySettings raises ValidationError if PUBLIC_KEY is missing."""
    with pytest.raises(ValidationError):
        IdentitySettings(PRIVATE_KEY="some-key")  # ty: ignore[missing-argument]  # intentional


def test_settings_defaults():
    """IdentitySettings has correct defaults for token expiry and rate limits."""
    s = IdentitySettings(PRIVATE_KEY="pk", PUBLIC_KEY="pub")
    assert s.ACCESS_TOKEN_EXPIRE_MINUTES == 15
    assert s.REFRESH_TOKEN_EXPIRE_DAYS == 7
    assert s.RATE_LIMIT_LOGIN_PER_MINUTE == 5
    assert s.RATE_LIMIT_LOGIN_PER_HOUR_PER_EMAIL == 10
    assert s.REDIS_URL == "redis://localhost:6379/0"


def test_settings_env_prefix():
    """IdentitySettings uses IDENTITY__ prefix for env vars."""
    os.environ["IDENTITY__ACCESS_TOKEN_EXPIRE_MINUTES"] = "30"
    try:
        s = IdentitySettings(PRIVATE_KEY="pk", PUBLIC_KEY="pub")
        assert s.ACCESS_TOKEN_EXPIRE_MINUTES == 30
    finally:
        del os.environ["IDENTITY__ACCESS_TOKEN_EXPIRE_MINUTES"]
