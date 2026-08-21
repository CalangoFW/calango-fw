from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import time
from collections.abc import AsyncGenerator
from importlib.metadata import entry_points
from pathlib import Path
from uuid import uuid4

import pytest
from calango_identity.plugin import IdentityPlugin
from calango_identity.refresh_tokens import InMemoryRefreshTokenStore
from calango_identity.settings import IdentitySettings
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine
from tests.conftest import TEST_PRIVATE_KEY, TEST_PUBLIC_KEY

from calango_cli.migrations import version_locations

IDENTITY_TABLES = {
    "identity_permissions",
    "identity_role_permissions",
    "identity_roles",
    "identity_user_roles",
    "identity_users",
}
POSTGRES_URL_ENV = "CALANGO_TEST_POSTGRES_URL"


def test_identity_plugin_entry_point_is_installed():
    matches = tuple(
        entry_point
        for entry_point in entry_points(group="calango.plugins")
        if entry_point.name == "identity"
    )

    assert len(matches) == 1
    assert matches[0].load() is IdentityPlugin


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
async def postgres_url() -> AsyncGenerator[str, None]:
    configured_url = os.getenv(POSTGRES_URL_ENV)
    if configured_url:
        yield configured_url
        return

    if not _docker_is_available():
        pytest.skip(f"set {POSTGRES_URL_ENV} or provide a reachable Docker daemon for PostgreSQL")

    name = f"calango-migrations-{uuid4().hex}"
    container_id = _docker(
        "run",
        "--detach",
        "--rm",
        "--name",
        name,
        "--publish",
        "127.0.0.1::5432",
        "--env",
        "POSTGRES_USER=calango",
        "--env",
        "POSTGRES_PASSWORD=calango",
        "--env",
        "POSTGRES_DB=calango_test",
        "--health-cmd",
        "pg_isready -U calango -d calango_test",
        "--health-interval",
        "250ms",
        "--health-timeout",
        "2s",
        "--health-retries",
        "40",
        "postgres:16-alpine",
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
            log_result = _docker("logs", container_id, check=False)
            logs = log_result.stdout + log_result.stderr
            if health == "healthy" and logs.count("ready to accept connections") >= 2:
                break
            await asyncio.sleep(0.25)
        else:
            pytest.fail(f"temporary PostgreSQL did not become healthy: {logs[-2000:]}")

        port = _docker("port", container_id, "5432/tcp").stdout.strip().rsplit(":", 1)[1]
        yield f"postgresql+asyncpg://calango:calango@127.0.0.1:{port}/calango_test"
    finally:
        _docker("rm", "--force", container_id, check=False)


async def _table_names(url: str) -> set[str]:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            return set(await connection.run_sync(lambda sync: inspect(sync).get_table_names()))
    finally:
        await engine.dispose()


def _run_alembic(url: str, command_name: str, revision: str, versions: Path) -> None:
    from alembic import command
    from alembic.config import Config

    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parents[1] / "alembic"))
    config.set_main_option("version_locations", str(versions))
    config.set_main_option("path_separator", "os")
    config.set_main_option("sqlalchemy.url", url)
    getattr(command, command_name)(config, revision)


async def test_identity_upgrade_and_downgrade(postgres_url):
    plugin = IdentityPlugin(
        settings=IdentitySettings(PRIVATE_KEY=TEST_PRIVATE_KEY, PUBLIC_KEY=TEST_PUBLIC_KEY),
        refresh_store=InMemoryRefreshTokenStore(),
    )
    versions = version_locations(plugin.migrations())[0]

    await asyncio.to_thread(_run_alembic, postgres_url, "upgrade", "heads", versions)
    assert await _table_names(postgres_url) >= IDENTITY_TABLES

    await asyncio.to_thread(_run_alembic, postgres_url, "downgrade", "base", versions)
    assert not (await _table_names(postgres_url) & IDENTITY_TABLES)
