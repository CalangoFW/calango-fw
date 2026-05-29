from __future__ import annotations

from calango_identity.rate_limit import get_email_key, make_limiter
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded


def test_make_limiter_returns_limiter():
    """make_limiter() returns a slowapi Limiter instance."""
    limiter = make_limiter("memory://")
    assert isinstance(limiter, Limiter)


def test_get_email_key_returns_email_from_state():
    """get_email_key returns login_email from request.state when present."""
    # Simulate a request with login_email set on state
    state = type("State", (), {"login_email": "a@b.com"})()
    request = type("Req", (), {"state": state, "client": type("C", (), {"host": "127.0.0.1"})()})()
    key = get_email_key(request)
    assert key == "a@b.com"


def test_get_email_key_falls_back_to_ip():
    """get_email_key falls back to IP address when login_email is not on state."""
    state = type("State", (), {})()  # no login_email
    request = type("Req", (), {
        "state": state,
        "client": type("C", (), {"host": "1.2.3.4"})(),
        "headers": {},
    })()
    key = get_email_key(request)
    # Should return something (IP or similar), not crash
    assert key is not None
    assert isinstance(key, str)


async def test_rate_limit_blocks_after_threshold():
    """Endpoint decorated with limiter blocks requests after the threshold."""
    from slowapi import _rate_limit_exceeded_handler

    limiter = make_limiter("memory://")
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    @app.get("/limited")
    @limiter.limit("2/minute")
    async def limited_endpoint(request: Request):
        return {"ok": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r1 = await client.get("/limited")
        r2 = await client.get("/limited")
        r3 = await client.get("/limited")  # should be blocked

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r3.status_code == 429
