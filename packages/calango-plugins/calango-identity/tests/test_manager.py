from __future__ import annotations

import jwt
from calango_identity.manager import UserManager


def test_reset_and_verification_tokens_use_dedicated_hmac_secrets(identity_settings):
    # The manager only derives secrets here; it never touches the user database.
    manager = UserManager(None, identity_settings)  # ty: ignore[invalid-argument-type]
    reset_secret = manager.reset_password_token_secret
    verification_secret = manager.verification_token_secret
    private_key = identity_settings.PRIVATE_KEY.get_secret_value()

    assert reset_secret != verification_secret
    for secret in (reset_secret, verification_secret):
        assert isinstance(secret, str)
        assert secret != private_key
        # FastAPI Users signs these tokens with HS256; PyJWT rejects PEM keys there.
        jwt.encode({"sub": "user"}, secret, algorithm="HS256")
