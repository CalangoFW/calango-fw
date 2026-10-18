from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from calango_identity.models import Base
from calango_identity.plugin import IdentityPlugin
from calango_identity.settings import IdentitySettings
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from tests.conftest import TEST_PRIVATE_KEY, TEST_PUBLIC_KEY

from calango import Calango
from calango.core.database import DatabaseRuntime

pytestmark = pytest.mark.integration

CREDENTIALS = {"username": "redis-outage@example.com", "password": "SecurePassword123!"}


@pytest.fixture
async def redis_identity_client(
    disposable_redis,
) -> AsyncGenerator[AsyncClient, None]:
    redis_address = disposable_redis.address
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def get_db():
        async with session_factory() as session:
            yield session

    app = Calango()
    app.database = DatabaseRuntime(app.settings, session_dependency=get_db)
    app.include_plugin(
        IdentityPlugin(
            settings=IdentitySettings(
                PRIVATE_KEY=TEST_PRIVATE_KEY,
                PUBLIC_KEY=TEST_PUBLIC_KEY,
                REDIS_URL=f"redis://{redis_address}/0",
            )
        )
    )
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    await engine.dispose()


async def test_redis_outage_returns_uniform_503_from_every_session_endpoint(
    disposable_redis,
    redis_identity_client: AsyncClient,
):
    redis_address = disposable_redis.address
    client = redis_identity_client
    registered = await client.post(
        "/auth/register",
        json={"email": CREDENTIALS["username"], "password": CREDENTIALS["password"]},
    )
    assert registered.status_code == 201, registered.text
    login = await client.post("/auth/login", data=CREDENTIALS)
    assert login.status_code == 200, login.text
    refresh_token = login.json()["refresh_token"]

    disposable_redis.stop()

    responses = {
        "login": await client.post("/auth/login", data=CREDENTIALS),
        "refresh": await client.post("/auth/refresh", json={"refresh_token": refresh_token}),
        "logout": await client.post("/auth/logout", json={"refresh_token": refresh_token}),
    }
    for endpoint, response in responses.items():
        assert response.status_code == 503, (endpoint, response.text)
        assert response.json()["error"] == "service_unavailable"
        assert response.json()["message"] == "Authentication service unavailable"
        for secret in (redis_address, refresh_token, CREDENTIALS["username"]):
            assert secret not in response.text, endpoint
