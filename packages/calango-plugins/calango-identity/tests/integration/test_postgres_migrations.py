from __future__ import annotations

import asyncio
from importlib.metadata import entry_points

import pytest
from calango_identity.plugin import IdentityPlugin
from calango_identity.refresh_tokens import InMemoryRefreshTokenStore
from calango_identity.settings import IdentitySettings
from calango_plugin_base import PluginMigration
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
pytestmark = pytest.mark.integration


def test_identity_plugin_entry_point_is_installed():
    matches = tuple(
        entry_point
        for entry_point in entry_points(group="calango.plugins")
        if entry_point.name == "identity"
    )

    assert len(matches) == 1
    assert matches[0].load() is IdentityPlugin


async def _table_names(url: str) -> set[str]:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            return set(await connection.run_sync(lambda sync: inspect(sync).get_table_names()))
    finally:
        await engine.dispose()


async def test_identity_upgrade_and_downgrade(postgres_url, migration_resources, run_alembic):
    plugin = IdentityPlugin(
        settings=IdentitySettings(PRIVATE_KEY=TEST_PRIVATE_KEY, PUBLIC_KEY=TEST_PUBLIC_KEY),
        refresh_store=InMemoryRefreshTokenStore(),
    )
    versions = version_locations(plugin.migrations(), resources=migration_resources)[0]

    await asyncio.to_thread(run_alembic, postgres_url, "upgrade", "heads", versions)
    assert await _table_names(postgres_url) >= IDENTITY_TABLES

    await asyncio.to_thread(run_alembic, postgres_url, "downgrade", "base", versions)
    assert not (await _table_names(postgres_url) & IDENTITY_TABLES)


async def test_plugin_dependency_executes_after_required_plugin(
    postgres_url,
    tmp_path,
    migration_resources,
    run_alembic,
):
    base_versions = tmp_path / "base_versions"
    dependent_versions = tmp_path / "dependent_versions"
    independent_versions = tmp_path / "independent_versions"
    required_versions = tmp_path / "required_versions"
    base_versions.mkdir()
    dependent_versions.mkdir()
    independent_versions.mkdir()
    required_versions.mkdir()
    (base_versions / "0001_base.py").write_text(
        "from alembic import op\n"
        "import sqlalchemy as sa\n"
        "revision = 'zzz_base_0001'\n"
        "down_revision = None\n"
        "branch_labels = None\n"
        "depends_on = None\n"
        "def upgrade():\n"
        "    op.create_table('plugin_migration_order', "
        "sa.Column('id', sa.Integer(), primary_key=True), "
        "sa.Column('label', sa.String(32), nullable=False))\n"
        '    op.execute("INSERT INTO plugin_migration_order (id, label) '
        "VALUES (1, 'base')\")\n"
        "def downgrade():\n"
        "    op.drop_table('plugin_migration_order')\n"
    )
    (dependent_versions / "0001_dependent.py").write_text(
        "from alembic import op\n"
        "revision = 'aaa_dependent_0001'\n"
        "down_revision = None\n"
        "branch_labels = None\n"
        "depends_on = None\n"
        "def upgrade():\n"
        '    op.execute("INSERT INTO plugin_migration_order (id, label) '
        "VALUES (2, 'dependent')\")\n"
        "def downgrade():\n"
        '    op.execute("DELETE FROM plugin_migration_order WHERE id = 2")\n'
    )
    (dependent_versions / "0002_dependent_child.py").write_text(
        "from alembic import op\n"
        "revision = 'dependent_0002'\n"
        "down_revision = 'aaa_dependent_0001'\n"
        "branch_labels = None\n"
        "depends_on = None\n"
        "def upgrade():\n"
        '    op.execute("INSERT INTO plugin_migration_order (id, label) '
        "VALUES (3, 'child')\")\n"
        "def downgrade():\n"
        '    op.execute("DELETE FROM plugin_migration_order WHERE id = 3")\n'
    )
    (independent_versions / "0001_independent.py").write_text(
        "from alembic import op\n"
        "import sqlalchemy as sa\n"
        "revision = 'independent_0001'\n"
        "down_revision = None\n"
        "branch_labels = None\n"
        "depends_on = None\n"
        "def upgrade():\n"
        "    op.create_table('independent_marker', "
        "sa.Column('id', sa.Integer(), primary_key=True))\n"
        "def downgrade():\n"
        "    op.drop_table('independent_marker')\n"
    )
    (required_versions / "0001_required.py").write_text(
        "from alembic import op\n"
        "import sqlalchemy as sa\n"
        "revision = 'required_0001'\n"
        "down_revision = None\n"
        "branch_labels = None\n"
        "depends_on = None\n"
        "def upgrade():\n"
        "    op.create_table('required_marker', "
        "sa.Column('id', sa.Integer(), primary_key=True))\n"
        "def downgrade():\n"
        "    op.drop_table('required_marker')\n"
    )
    items = (
        PluginMigration("dependent", dependent_versions, ("base", "required")),
        PluginMigration("independent", independent_versions, ()),
        PluginMigration("required", required_versions, ()),
        PluginMigration("base", base_versions, ()),
    )
    locations = version_locations(items, resources=migration_resources)

    await asyncio.to_thread(run_alembic, postgres_url, "upgrade", "heads", locations)
    engine = create_async_engine(postgres_url)
    try:
        async with engine.connect() as connection:
            labels = tuple(
                await connection.run_sync(
                    lambda sync: sync.exec_driver_sql(
                        "SELECT label FROM plugin_migration_order ORDER BY id"
                    ).scalars()
                )
            )
    finally:
        await engine.dispose()

    assert labels == ("base", "dependent", "child")
    assert "independent_marker" in await _table_names(postgres_url)

    await asyncio.to_thread(
        run_alembic,
        postgres_url,
        "downgrade",
        "dependent_0002@-1",
        locations,
    )
    await asyncio.to_thread(
        run_alembic,
        postgres_url,
        "downgrade",
        "aaa_dependent_0001@required_0001",
        locations,
    )
    await asyncio.to_thread(
        run_alembic,
        postgres_url,
        "downgrade",
        "independent_0001@-1",
        locations,
    )
    assert "independent_marker" not in await _table_names(postgres_url)
    assert "required_marker" in await _table_names(postgres_url)
    engine = create_async_engine(postgres_url)
    try:
        async with engine.connect() as connection:
            labels = tuple(
                await connection.run_sync(
                    lambda sync: sync.exec_driver_sql(
                        "SELECT label FROM plugin_migration_order ORDER BY id"
                    ).scalars()
                )
            )
    finally:
        await engine.dispose()
    assert labels == ("base",)

    await asyncio.to_thread(run_alembic, postgres_url, "downgrade", "base", locations)


async def test_redundant_plugin_dependency_rolls_back_only_dependent(
    postgres_url,
    tmp_path,
    migration_resources,
    run_alembic,
):
    versions_by_name = {name: tmp_path / f"{name}_versions" for name in ("a", "b", "c")}
    for location in versions_by_name.values():
        location.mkdir()
    (versions_by_name["a"] / "0001_a.py").write_text(
        "from alembic import op\n"
        "import sqlalchemy as sa\n"
        "revision = 'a_0001'\n"
        "down_revision = None\n"
        "branch_labels = None\n"
        "depends_on = None\n"
        "def upgrade():\n"
        "    op.create_table('redundant_dependency_order', "
        "sa.Column('id', sa.Integer(), primary_key=True), "
        "sa.Column('label', sa.String(8), nullable=False))\n"
        '    op.execute("INSERT INTO redundant_dependency_order (id, label) VALUES (1, '
        "'a')\")\n"
        "def downgrade():\n"
        "    op.drop_table('redundant_dependency_order')\n"
    )
    for index, name in enumerate(("b", "c"), start=2):
        (versions_by_name[name] / f"0001_{name}.py").write_text(
            "from alembic import op\n"
            f"revision = '{name}_0001'\n"
            "down_revision = None\n"
            "branch_labels = None\n"
            "depends_on = None\n"
            "def upgrade():\n"
            f'    op.execute("INSERT INTO redundant_dependency_order (id, label) '
            f"VALUES ({index}, '{name}')\")\n"
            "def downgrade():\n"
            f'    op.execute("DELETE FROM redundant_dependency_order WHERE id = {index}")\n'
        )
    locations = version_locations(
        (
            PluginMigration("a", versions_by_name["a"], ()),
            PluginMigration("b", versions_by_name["b"], ("a",)),
            PluginMigration("c", versions_by_name["c"], ("a", "b")),
        ),
        resources=migration_resources,
    )

    await asyncio.to_thread(run_alembic, postgres_url, "upgrade", "heads", locations)
    engine = create_async_engine(postgres_url)
    try:
        async with engine.connect() as connection:
            labels = tuple(
                await connection.run_sync(
                    lambda sync: sync.exec_driver_sql(
                        "SELECT label FROM redundant_dependency_order ORDER BY id"
                    ).scalars()
                )
            )
    finally:
        await engine.dispose()
    assert labels == ("a", "b", "c")

    await asyncio.to_thread(run_alembic, postgres_url, "downgrade", "c_0001@-1", locations)
    engine = create_async_engine(postgres_url)
    try:
        async with engine.connect() as connection:
            labels = tuple(
                await connection.run_sync(
                    lambda sync: sync.exec_driver_sql(
                        "SELECT label FROM redundant_dependency_order ORDER BY id"
                    ).scalars()
                )
            )
    finally:
        await engine.dispose()
    assert labels == ("a", "b")

    await asyncio.to_thread(run_alembic, postgres_url, "downgrade", "base", locations)
