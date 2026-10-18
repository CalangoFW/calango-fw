from __future__ import annotations

import asyncio
import os
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from calango_identity.plugin import IdentityPlugin
from calango_identity.refresh_tokens import InMemoryRefreshTokenStore
from calango_identity.settings import IdentitySettings
from tests.conftest import TEST_PRIVATE_KEY, TEST_PUBLIC_KEY

from calango_cli.migrations import MigrationResources, version_locations

AlembicRunner = Callable[[str, str, str, Path | tuple[Path, ...]], None]


def _run_alembic(
    url: str,
    command_name: str,
    revision: str,
    versions: Path | tuple[Path, ...],
) -> None:
    from alembic import command
    from alembic.config import Config

    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parents[1] / "alembic"))
    locations = (versions,) if isinstance(versions, Path) else versions
    config.set_main_option("version_locations", os.pathsep.join(map(str, locations)))
    config.set_main_option("path_separator", "os")
    config.set_main_option("sqlalchemy.url", url)
    getattr(command, command_name)(config, revision)


@pytest.fixture
def migration_resources() -> Iterator[MigrationResources]:
    with MigrationResources() as resources:
        yield resources


@pytest.fixture
def run_alembic() -> AlembicRunner:
    """Run an Alembic command against explicit version locations."""
    return _run_alembic


@pytest.fixture
async def identity_database(
    postgres_url: str,
    migration_resources: MigrationResources,
) -> str:
    """A PostgreSQL URL whose schema comes from Identity's shipped migration."""
    plugin = IdentityPlugin(
        settings=IdentitySettings(PRIVATE_KEY=TEST_PRIVATE_KEY, PUBLIC_KEY=TEST_PUBLIC_KEY),
        refresh_store=InMemoryRefreshTokenStore(),
    )
    versions = version_locations(plugin.migrations(), resources=migration_resources)[0]
    await asyncio.to_thread(_run_alembic, postgres_url, "upgrade", "heads", versions)
    return postgres_url
