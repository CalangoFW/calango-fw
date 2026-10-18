"""Real PostgreSQL and Redis services for integration tests.

Each service comes from an explicit URL (CI or a local server) or, when Docker
is reachable, from a disposable container started once per test session. Tests
that request a service which is unavailable are skipped, never silently faked.

``CALANGO_TEST_POSTGRES_URL`` must point at a throwaway database: every test
that uses ``postgres_url`` drops and recreates its ``public`` schema.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass
from uuid import uuid4

import pytest
import redis.asyncio as redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

POSTGRES_URL_ENV = "CALANGO_TEST_POSTGRES_URL"
REDIS_URL_ENV = "CALANGO_TEST_REDIS_URL"
_HEALTH_TIMEOUT_SECONDS = 30


def docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *args], check=check, capture_output=True, text=True)


def docker_is_available() -> bool:
    if shutil.which("docker") is None:
        return False
    return docker("info", check=False).returncode == 0


def _start_container(name: str, image: str, port: str, *options: str) -> tuple[str, str]:
    """Run a detached container and wait for its health check; return id and host port."""
    container_id = docker(
        "run",
        "--detach",
        "--rm",
        "--name",
        f"calango-test-{name}-{uuid4().hex}",
        "--publish",
        f"127.0.0.1::{port}",
        "--health-interval",
        "250ms",
        "--health-timeout",
        "2s",
        "--health-retries",
        "80",
        *options,
        image,
    ).stdout.strip()
    deadline = time.monotonic() + _HEALTH_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        health = docker(
            "inspect", "--format", "{{.State.Health.Status}}", container_id, check=False
        ).stdout.strip()
        if health == "healthy":
            host_port = docker("port", container_id, f"{port}/tcp").stdout.strip()
            return container_id, host_port.rsplit(":", 1)[1]
        time.sleep(0.25)
    logs = docker("logs", container_id, check=False)
    docker("rm", "--force", container_id, check=False)
    pytest.fail(f"temporary {name} did not become healthy: {(logs.stdout + logs.stderr)[-2000:]}")


def _service_or_skip(env_name: str, service: str) -> str | None:
    configured = os.getenv(env_name)
    if configured:
        return configured
    if not docker_is_available():
        pytest.skip(f"set {env_name} or provide a reachable Docker daemon for {service}")
    return None


@pytest.fixture(scope="session")
def postgres_server() -> Iterator[str]:
    configured = _service_or_skip(POSTGRES_URL_ENV, "PostgreSQL")
    if configured:
        yield configured
        return
    container_id, port = _start_container(
        "postgres",
        "postgres:16-alpine",
        "5432",
        "--env",
        "POSTGRES_USER=calango",
        "--env",
        "POSTGRES_PASSWORD=calango",
        "--env",
        "POSTGRES_DB=calango_test",
        "--health-cmd",
        # The init server also answers pg_isready; require the TCP listener.
        "pg_isready -h 127.0.0.1 -U calango -d calango_test",
    )
    try:
        yield f"postgresql+asyncpg://calango:calango@127.0.0.1:{port}/calango_test"
    finally:
        docker("rm", "--force", container_id, check=False)


@pytest.fixture
async def postgres_url(postgres_server: str) -> AsyncIterator[str]:
    """A PostgreSQL URL whose ``public`` schema is empty when the test starts."""
    engine = create_async_engine(postgres_server)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("DROP SCHEMA public CASCADE"))
            await connection.execute(text("CREATE SCHEMA public"))
    finally:
        await engine.dispose()
    yield postgres_server


@pytest.fixture(scope="session")
def redis_server() -> Iterator[str]:
    configured = _service_or_skip(REDIS_URL_ENV, "Redis")
    if configured:
        yield configured
        return
    container_id, port = _start_container(
        "redis", "redis:7-alpine", "6379", "--health-cmd", "redis-cli ping"
    )
    try:
        yield f"redis://127.0.0.1:{port}/0"
    finally:
        docker("rm", "--force", container_id, check=False)


@pytest.fixture
async def redis_url(redis_server: str) -> AsyncIterator[str]:
    """A Redis URL whose database is empty when the test starts."""
    client = redis.from_url(redis_server)
    try:
        await client.flushdb()
    finally:
        await client.aclose()
    yield redis_server


@dataclass(frozen=True)
class DisposableService:
    """A container owned by one test: its ``host:port`` and a way to kill it."""

    address: str
    stop: Callable[[], None]


@pytest.fixture
def disposable_redis() -> Iterator[DisposableService]:
    """A Redis container owned by one test, which may stop it to simulate an outage."""
    if not docker_is_available():
        pytest.skip("provide a reachable Docker daemon for a disposable Redis")
    container_id, port = _start_container(
        "redis-disposable", "redis:7-alpine", "6379", "--health-cmd", "redis-cli ping"
    )

    def stop() -> None:
        docker("stop", "--time", "0", container_id)

    try:
        yield DisposableService(address=f"127.0.0.1:{port}", stop=stop)
    finally:
        docker("rm", "--force", container_id, check=False)
