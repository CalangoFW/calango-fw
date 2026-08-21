from __future__ import annotations

import os

import pytest
from calango_identity.settings import IdentitySettings
from pydantic import ValidationError

from tests.conftest import TEST_PRIVATE_KEY, TEST_PUBLIC_KEY


@pytest.fixture
def valid_keys() -> dict[str, str]:
    return {"PRIVATE_KEY": TEST_PRIVATE_KEY, "PUBLIC_KEY": TEST_PUBLIC_KEY}


def test_settings_requires_private_key():
    """IdentitySettings raises ValidationError if PRIVATE_KEY is missing."""
    with pytest.raises(ValidationError):
        IdentitySettings(PUBLIC_KEY="some-key")  # ty: ignore[missing-argument]  # intentional


def test_settings_requires_public_key():
    """IdentitySettings raises ValidationError if PUBLIC_KEY is missing."""
    with pytest.raises(ValidationError):
        IdentitySettings(PRIVATE_KEY="some-key")  # ty: ignore[missing-argument]  # intentional


def test_settings_defaults(valid_keys):
    """IdentitySettings has correct defaults for token expiry and rate limits."""
    s = IdentitySettings(**valid_keys)
    assert s.ACCESS_TOKEN_EXPIRE_MINUTES == 15
    assert s.REFRESH_TOKEN_EXPIRE_DAYS == 7
    assert s.RATE_LIMIT_LOGIN_PER_MINUTE == 5
    assert s.RATE_LIMIT_LOGIN_PER_HOUR_PER_EMAIL == 10
    assert s.REDIS_URL == "redis://localhost:6379/0"
    assert s.TRUSTED_PROXIES == ()


def test_settings_env_prefix(valid_keys):
    """IdentitySettings uses IDENTITY__ prefix for env vars."""
    os.environ["IDENTITY__ACCESS_TOKEN_EXPIRE_MINUTES"] = "30"
    try:
        s = IdentitySettings(**valid_keys)
        assert s.ACCESS_TOKEN_EXPIRE_MINUTES == 30
    finally:
        del os.environ["IDENTITY__ACCESS_TOKEN_EXPIRE_MINUTES"]


@pytest.mark.parametrize(
    "field",
    [
        "ACCESS_TOKEN_EXPIRE_MINUTES",
        "REFRESH_TOKEN_EXPIRE_DAYS",
        "RATE_LIMIT_LOGIN_PER_MINUTE",
        "RATE_LIMIT_LOGIN_PER_HOUR_PER_EMAIL",
    ],
)
def test_settings_reject_non_positive_security_values(field, valid_keys):
    """Security durations and rate limits must be strictly positive."""
    with pytest.raises(ValidationError):
        IdentitySettings(**valid_keys, **{field: 0})


def test_settings_rejects_blank_refresh_token_key_prefix(valid_keys):
    """Refresh-token Redis keys must always retain a nonblank namespace."""
    with pytest.raises(ValidationError):
        IdentitySettings(**valid_keys, REFRESH_TOKEN_KEY_PREFIX=" \t\n ")


@pytest.mark.parametrize("field", ["PRIVATE_KEY", "PUBLIC_KEY"])
def test_settings_rejects_invalid_pem_keys(field, valid_keys):
    """Identity startup must reject a malformed signing or verification key."""
    with pytest.raises(ValidationError):
        IdentitySettings(**(valid_keys | {field: "not a PEM key"}))


def test_settings_normalizes_trusted_proxies_to_tuple(valid_keys):
    """Trusted proxy configuration is immutable after settings startup."""
    settings = IdentitySettings(
        **valid_keys,
        TRUSTED_PROXIES=["10.0.0.0/8", "192.0.2.10"],  # ty: ignore[invalid-argument-type]  # Pydantic coerces config sequences.
    )

    assert settings.TRUSTED_PROXIES == ("10.0.0.0/8", "192.0.2.10")
