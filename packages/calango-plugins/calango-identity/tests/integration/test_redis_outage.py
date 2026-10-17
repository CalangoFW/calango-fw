from __future__ import annotations

import asyncio
import shutil
import subprocess
import time
from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
from calango_identity.models import Base
from calango_identity.plugin import IdentityPlugin
from calango_identity.settings import IdentitySettings
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from tests.conftest import TEST_PRIVATE_KEY, TEST_PUBLIC_KEY

from calango import Calango
from calango.core.database import DatabaseRuntime

CREDENTIALS = {"username": "redis-outage@example.com", "password": "SecurePassword123!"}


def _docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args],
        check=check,
        capture_output=True,
        text=True,
    )


def _docker_is_available() -> bool:
    if shutil.which("docker") is None:
        return False
    return _docker("info", check=False).returncode == 0


@pytest.fixture
async def redis_container() -> AsyncGenerator[tuple[str, str], None]:
    """Yield a disposable Redis the test can stop; a shared server cannot be."""
    if not _docker_is_available():
        pytest.skip("provide a reachable Docker daemon to run the Redis outage test")

    container_id = _docker(
        "run",
        "--detach",
        "--rm",
        "--name",
        f"calango-redis-outage-{uuid4().hex}",
        "--publish",
        "127.0.0.1::6379",
        "--health-cmd",
        "redis-cli ping",
        "--health-interval",
        "250ms",
        "--health-timeout",
        "2s",
        "--health-retries",
        "40",
        "redis:7-alpine",
    ).stdout.strip()
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            health = _docker(
                "inspect",
                "--format",
                "{{.State.Health.Status}}",
                container_id,
                check=False,
            ).stdout.strip()
            if health == "healthy":
                break
            await asyncio.sleep(0.25)
        else:
            pytest.fail("temporary Redis did not become healthy")

        port = _docker("port", container_id, "6379/tcp").stdout.strip().rsplit(":", 1)[1]
        yield container_id, f"127.0.0.1:{port}"
    finally:
        _docker("rm", "--force", container_id, check=False)


@pytest.fixture
async def redis_identity_client(
    redis_container: tuple[str, str],
) -> AsyncGenerator[AsyncClient, None]:
    _, redis_address = redis_container
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
    redis_container: tuple[str, str],
    redis_identity_client: AsyncClient,
):
    container_id, redis_address = redis_container
    client = redis_identity_client
    registered = await client.post(
        "/auth/register",
        json={"email": CREDENTIALS["username"], "password": CREDENTIALS["password"]},
    )
    assert registered.status_code == 201, registered.text
    login = await client.post("/auth/login", data=CREDENTIALS)
    assert login.status_code == 200, login.text
    refresh_token = login.json()["refresh_token"]

    _docker("stop", "--time", "0", container_id)

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
