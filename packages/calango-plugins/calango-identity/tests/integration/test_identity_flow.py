"""Identity end to end on real PostgreSQL (via its migration) and Redis."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import aclosing
from dataclasses import dataclass, field

import pytest
import redis.asyncio as redis
from calango_identity import IdentityPlugin, IdentitySettings, User, public, require_permission
from calango_identity.models import Permission, Role
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from tests.conftest import TEST_PRIVATE_KEY, TEST_PUBLIC_KEY

from calango import Calango
from calango.config import CalangoSettings, DatabaseSettings, SecuritySettings

pytestmark = pytest.mark.integration

PASSWORD = "SecurePassword123!"
NEW_PASSWORD = "AnotherSecurePassword456!"
PER_IP_LIMIT = 3
PER_EMAIL_LIMIT = 4


@dataclass
class DeliveryRecorder:
    """Identity events provider that keeps delivered reset tokens."""

    fail: bool = False
    password_resets: list[tuple[str, str]] = field(default_factory=list)

    async def on_registered(self, user, request) -> None:
        pass

    async def on_login(self, user, request, response) -> None:
        pass

    async def send_password_reset(self, user, token: str, request) -> None:
        if self.fail:
            raise RuntimeError("delivery provider outage")
        self.password_resets.append((user.email, token))

    async def send_verification(self, user, token: str, request) -> None:
        pass


def build_app(database_url: str, redis_url: str, events: DeliveryRecorder) -> Calango:
    app = Calango(
        settings=CalangoSettings(
            database=DatabaseSettings(URL=database_url),
            security=SecuritySettings(SECRET_KEY="integration-secret"),
        )
    )

    @app.get("/private")
    async def private_route():
        return {"private": True}

    @app.get("/open")
    @public
    async def open_route():
        return {"open": True}

    @app.get("/reports")
    async def reports(user: User = require_permission("reports:view")):  # noqa: B008
        return {"user": user.email}

    mounted = FastAPI()

    @mounted.get("/")
    async def mounted_root():
        return {"mounted": True}

    app.mount("/mounted", mounted)
    app.include_plugin(
        IdentityPlugin(
            settings=IdentitySettings(
                PRIVATE_KEY=TEST_PRIVATE_KEY,
                PUBLIC_KEY=TEST_PUBLIC_KEY,
                REDIS_URL=redis_url,
                RATE_LIMIT_LOGIN_PER_MINUTE=PER_IP_LIMIT,
                RATE_LIMIT_LOGIN_PER_HOUR_PER_EMAIL=PER_EMAIL_LIMIT,
            ),
            events=events,
            enable_password_reset=True,
        )
    )
    return app


@dataclass
class Flow:
    app: Calango
    events: DeliveryRecorder

    def client(self, ip: str = "127.0.0.1") -> AsyncClient:
        transport = ASGITransport(app=self.app, client=(ip, 50000))
        return AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture
async def flow(identity_database: str, redis_url: str) -> AsyncIterator[Flow]:
    events = DeliveryRecorder()
    app = build_app(identity_database, redis_url, events)
    async with app.router.lifespan_context(app):
        yield Flow(app, events)


async def register(client: AsyncClient, email: str) -> None:
    response = await client.post("/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201, response.text


async def login(client: AsyncClient, email: str, password: str = PASSWORD):
    return await client.post("/auth/login", data={"username": email, "password": password})


def bearer(tokens: dict[str, str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


async def grant_permission(app: Calango, email: str, code: str) -> None:
    async with aclosing(app.database.session()) as sessions:
        async for session in sessions:
            user = await session.scalar(select(User).filter_by(email=email))
            assert user is not None
            session.add(
                Role(name=f"{code}-role", users=[user], permissions=[Permission(code=code)])
            )
            await session.commit()


async def test_session_lifecycle_across_every_boundary(flow: Flow):
    async with flow.client() as client:
        await register(client, "lifecycle@example.com")
        duplicate = await client.post(
            "/auth/register",
            json={"email": "lifecycle@example.com", "password": PASSWORD},
        )
        assert duplicate.status_code == 400

        logged_in = await login(client, "lifecycle@example.com")
        assert logged_in.status_code == 200, logged_in.text
        assert logged_in.headers["cache-control"] == "no-store"
        tokens = logged_in.json()

        assert (await client.get("/private")).status_code == 401
        assert (await client.get("/private", headers=bearer(tokens))).status_code == 200
        assert (await client.get("/open")).status_code == 200
        assert (await client.get("/mounted/")).status_code == 401
        assert (await client.get("/mounted/", headers=bearer(tokens))).status_code == 200

        assert (await client.get("/reports")).status_code == 401
        assert (await client.get("/reports", headers=bearer(tokens))).status_code == 403
        await grant_permission(flow.app, "lifecycle@example.com", "reports:view")
        assert (await client.get("/reports", headers=bearer(tokens))).status_code == 200

        rotated = await client.post(
            "/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
        assert rotated.status_code == 200, rotated.text
        assert rotated.headers["cache-control"] == "no-store"
        refresh_token = rotated.json()["refresh_token"]
        assert refresh_token != tokens["refresh_token"]

        logout = await client.post("/auth/logout", json={"refresh_token": refresh_token})
        assert logout.status_code == 204
        after_logout = await client.post("/auth/refresh", json={"refresh_token": refresh_token})
        assert after_logout.status_code == 401


async def test_concurrent_refresh_reuse_revokes_the_whole_family(flow: Flow):
    async with flow.client() as client:
        await register(client, "reuse@example.com")
        refresh_token = (await login(client, "reuse@example.com")).json()["refresh_token"]

        first, second = await asyncio.gather(
            client.post("/auth/refresh", json={"refresh_token": refresh_token}),
            client.post("/auth/refresh", json={"refresh_token": refresh_token}),
        )
        assert sorted([first.status_code, second.status_code]) == [200, 401]
        winner = first if first.status_code == 200 else second

        revoked = await client.post(
            "/auth/refresh", json={"refresh_token": winner.json()["refresh_token"]}
        )
        assert revoked.status_code == 401


async def test_login_limits_apply_per_client_ip_and_per_email(flow: Flow):
    async with flow.client("198.51.100.10") as client:
        statuses = [
            (await login(client, f"unknown-{attempt}@example.com")).status_code
            for attempt in range(PER_IP_LIMIT + 1)
        ]
    assert statuses == [401] * PER_IP_LIMIT + [429]

    statuses = []
    for attempt in range(PER_EMAIL_LIMIT + 1):
        async with flow.client(f"203.0.113.{attempt + 1}") as client:
            statuses.append((await login(client, " Target@Example.com ")).status_code)
    assert statuses == [401] * PER_EMAIL_LIMIT + [429]


async def test_password_reset_delivers_a_usable_token(flow: Flow):
    async with flow.client() as client:
        await register(client, "reset@example.com")
        accepted = await client.post("/auth/forgot-password", json={"email": "reset@example.com"})
        assert accepted.status_code == 202
        [(email, token)] = flow.events.password_resets
        assert email == "reset@example.com"

        reset = await client.post(
            "/auth/reset-password", json={"token": token, "password": NEW_PASSWORD}
        )
        assert reset.status_code == 200, reset.text
        assert (await login(client, "reset@example.com")).status_code == 401
        assert (await login(client, "reset@example.com", NEW_PASSWORD)).status_code == 200


async def test_reset_provider_failure_is_indistinguishable_from_unknown_email(flow: Flow):
    flow.events.fail = True
    async with flow.client() as client:
        await register(client, "known@example.com")
        known = await client.post("/auth/forgot-password", json={"email": "known@example.com"})
        unknown = await client.post("/auth/forgot-password", json={"email": "nobody@example.com"})

    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()


async def test_shutdown_releases_redis_and_database_resources(
    identity_database: str,
    redis_url: str,
):
    admin = redis.from_url(redis_url)
    try:
        baseline = (await admin.info("clients"))["connected_clients"]
        app = build_app(identity_database, redis_url, DeliveryRecorder())
        async with app.router.lifespan_context(app):
            async with Flow(app, DeliveryRecorder()).client() as client:
                await register(client, "shutdown@example.com")
                assert (await login(client, "shutdown@example.com")).status_code == 200
            assert (await admin.info("clients"))["connected_clients"] > baseline
            assert app.database.started

        assert not app.database.started
        for _ in range(40):
            if (await admin.info("clients"))["connected_clients"] == baseline:
                break
            await asyncio.sleep(0.05)
        assert (await admin.info("clients"))["connected_clients"] == baseline
    finally:
        await admin.aclose()
