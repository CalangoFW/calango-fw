from __future__ import annotations

import pytest
from calango_identity.settings import IdentitySettings

# Test RSA keys — generated with openssl genrsa 2048 / openssl rsa -pubout
# NEVER use these in production.
TEST_PRIVATE_KEY = """-----BEGIN PRIVATE KEY-----
MIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQCGj391F1ehg538
c3DiK4Z3+pQ+96YhZF6UEY+JlSzkXIc6l64Ze1nOCRziuHkuObN0TS2vHn6Ftf7c
WQPF32AsPWVdj1EevHtRidybz00WArsmxCA/6XwznIN3V/ROR2yLdGSCxjaDCe5c
77a/FOPLCbMj8eMQCebDmr5Y7k5otziyLvkKwe1Ioicmh4Re2u2H4B5VM0TkAWM+
9s3gRkP/sj3OwIA53TGkI5kaAnbIZmJW3hDAS2dylQvC8O/HUG/SZkCwfCIB8BKC
C0zHVrd72Ew/dVjMqI/2jDxII+ZY7PIEcPZErzzSK67IbyUK0XnzOiI1u8mF53tQ
+HtCcUF/AgMBAAECggEAEZEyZqsBecihG5BGsIBWMdu49u+F9N4RqusP/jpHfhjG
XtPmmtULyGZQKxlCWNKXpxtcV3x3sCUufL3yTCb5e00YqrpHMOgSgXaqIn1R5wm8
PTdlrnJhEKviTfZhosaYWSx84sXV4A2v3No+1Xt4sc02Yf72UeW5Bthw+VNDUVBJ
1FkCFMTUosn61gTF6UejDcDQRYyib2qF1CNwg2V4xttUo3TLwQKAm965YUnfP+V8
Mae6D55Kqn98yi4rEacDmZGfK5bKp4aWQ1kPyIW3MjztZ0nriZ5vNwN13GgTPnfT
bJr+Xq6zb4AqMbIdKtvTUBCo40viKtQGbsKU4TcW4QKBgQC5/Fp0ra6gnUrbqS31
trrI0lnn+XgsmQUnSvey+94hcY2d+3Y4zwsCXEeK+NBwX5qmsEN6RPRdBjsX5skB
UH+FOuVqOdkKnhrMOe78XUHxtIIHFskAUbGEt23QqupLh2Z37RN1XkVH7kwtryKA
b45u0XM+0IiB5VCgtoZk1FaIgwKBgQC5Nz3Dve5Gk69zs+/CqDLsaroYAg/UjSQN
E+nm3YaHb/re0H6aitQNGa6ohOm4kCY1wJPGQSn4zm0ffnngWNVOoOvuXRYJ6o7Z
Et9NX/ul0y6L4nCozQIHnN6aiJTuwlp/OYWgr3KhSUF5JOY6qKL2q2mB+bPk7ZlU
WzkhNSL6VQKBgQCf/mDqYscI0IcnNACfkhRY0ewZzNf+tZxjUvCG/nj2mDLVpw7q
i+HSpAO/n4/gO75Uiulhc5QrukJ3q0dbZB5vRF065oy5v40aBvR6ENe70CbTZlx/
c8ecfhdwHLf1RYN2w3Gr0+8RlAPggPrTNiR3XKMhdE8aP2T+/EXc03WldQKBgBEM
zcnEJTgoBkG/cbXYp/9tf74QCocFiykNCT4wbF7xZwW16cGuQAEIuTRYL+/GjU3r
cW8Rtpxp3E/G489MPi6jz7Q8q3e0OPwwqY/E4zSLsUA9UyOm46Xxweg15IfqKkyF
7hAxtnq0dKuDQxJpTb8pXmgRpYbQfInwb9znuFWVAoGBAK/tv3e+Kc9mQl6iYw3H
67qhZPbk3+hDgeVoyQJaTJYgYQwRsvpECnRIT86POCC8cGvrs7vLQvd4TjX4WfnY
P3WEQUacyH6MivzDJY3uoZ9QxtKKsgJWIhpPSxf7NdRi6G65sTdRJnEIcD9ejYvo
u9uB1AejXvPtWUxs7l/FQO1n
-----END PRIVATE KEY-----
"""

TEST_PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAho9/dRdXoYOd/HNw4iuG
d/qUPvemIWRelBGPiZUs5FyHOpeuGXtZzgkc4rh5LjmzdE0trx5+hbX+3FkDxd9g
LD1lXY9RHrx7UYncm89NFgK7JsQgP+l8M5yDd1f0Tkdsi3RkgsY2gwnuXO+2vxTj
ywmzI/HjEAnmw5q+WO5OaLc4si75CsHtSKInJoeEXtrth+AeVTNE5AFjPvbN4EZD
/7I9zsCAOd0xpCOZGgJ2yGZiVt4QwEtncpULwvDvx1Bv0mZAsHwiAfASggtMx1a3
e9hMP3VYzKiP9ow8SCPmWOzyBHD2RK880iuuyG8lCtF58zoiNbvJhed7UPh7QnFB
fwIDAQAB
-----END PUBLIC KEY-----
"""


@pytest.fixture
def identity_settings() -> IdentitySettings:
    return IdentitySettings(
        PRIVATE_KEY=TEST_PRIVATE_KEY,
        PUBLIC_KEY=TEST_PUBLIC_KEY,
        REDIS_URL="redis://localhost:6379/99",
    )
