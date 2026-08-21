from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

import pytest
from calango_identity.settings import IdentitySettings
from pydantic import ValidationError

from tests.conftest import TEST_PRIVATE_KEY, TEST_PUBLIC_KEY


@pytest.fixture
def valid_keys() -> dict[str, str]:
    return {"PRIVATE_KEY": TEST_PRIVATE_KEY, "PUBLIC_KEY": TEST_PUBLIC_KEY}


def _contains_secret_marker(value: Any, marker: str, seen: set[int] | None = None) -> bool:
    """Recursively detect raw secret data, including reversible secret wrappers."""
    if isinstance(value, str):
        return marker in value

    seen = seen or set()
    if id(value) in seen:
        return False
    seen.add(id(value))

    getter = getattr(value, "get_secret_value", None)
    if callable(getter) and _contains_secret_marker(getter(), marker, seen):
        return True
    if isinstance(value, BaseException):
        return any(
            _contains_secret_marker(item, marker, seen)
            for item in (value.args, value.__cause__, value.__context__)
        )
    if isinstance(value, Mapping):
        return any(_contains_secret_marker(item, marker, seen) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_contains_secret_marker(item, marker, seen) for item in value)
    return False


def test_settings_requires_private_key():
    """IdentitySettings raises ValidationError if PRIVATE_KEY is missing."""
    with pytest.raises(ValidationError):
        IdentitySettings(PUBLIC_KEY="some-key")


def test_settings_requires_public_key():
    """IdentitySettings raises ValidationError if PUBLIC_KEY is missing."""
    with pytest.raises(ValidationError):
        IdentitySettings(PRIVATE_KEY="some-key")


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


@pytest.mark.parametrize(
    ("field", "secret_marker"),
    [
        ("PRIVATE_KEY", "PRIVATE_KEY_SECRET_MARKER"),
        ("PUBLIC_KEY", "PUBLIC_KEY_SECRET_MARKER"),
    ],
)
def test_settings_rejects_invalid_pem_keys_without_exposing_inputs(
    field, secret_marker, valid_keys
):
    """Identity startup must reject a malformed signing or verification key."""
    with pytest.raises(ValidationError) as error:
        IdentitySettings(**(valid_keys | {field: secret_marker}))

    assert field in str(error.value)
    assert field in error.value.json()
    assert secret_marker not in str(error.value)
    assert secret_marker not in repr(error.value.errors())
    assert secret_marker not in error.value.json()
    assert not _contains_secret_marker(error.value.errors(), secret_marker)
    assert error.value.__cause__ is None
    assert error.value.__context__ is None
    assert not _contains_secret_marker(error.value.__cause__, secret_marker)
    assert not _contains_secret_marker(error.value.__context__, secret_marker)


def test_settings_representation_and_dumps_redact_rsa_keys(valid_keys):
    """Configured RSA keys must not leak through routine settings serialization."""
    settings = IdentitySettings(**valid_keys)

    secret_markers = (TEST_PRIVATE_KEY.splitlines()[1], TEST_PUBLIC_KEY.splitlines()[1])
    for rendered in (
        repr(settings),
        repr(settings.model_dump()),
        settings.model_dump_json(),
    ):
        assert all(marker not in rendered for marker in secret_markers)


def test_settings_normalizes_trusted_proxies_to_tuple(valid_keys):
    """Trusted proxy configuration is immutable after settings startup."""
    settings = IdentitySettings(
        **valid_keys,
        TRUSTED_PROXIES=["10.0.0.0/8", "192.0.2.10"],
    )

    assert settings.TRUSTED_PROXIES == ("10.0.0.0/8", "192.0.2.10")


def test_settings_rejects_trusted_proxy_cidr_with_host_bits(valid_keys):
    """A typo in a proxy CIDR must not silently broaden the trusted network."""
    with pytest.raises(ValidationError):
        IdentitySettings(**valid_keys, TRUSTED_PROXIES=("10.42.7.9/8",))
