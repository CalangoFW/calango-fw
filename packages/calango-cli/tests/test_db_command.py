import os
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch
from zipfile import Path as ZipPath
from zipfile import ZipFile

import pytest
from calango_plugin_base import PluginMigration
from typer.testing import CliRunner

from calango_cli.main import app
from calango_cli.migrations import (
    MigrationConfigurationError,
    order_migrations,
    version_locations,
)

runner = CliRunner()


def _project(tmp_path: Path) -> Path:
    (tmp_path / "alembic.ini").write_text("[alembic]\n")
    (tmp_path / "app").mkdir()
    return tmp_path


def test_db_help_exits_0():
    assert runner.invoke(app, ["db", "--help"]).exit_code == 0


def test_db_migrate_runs_upgrade_head(tmp_path):
    _project(tmp_path)
    with patch("calango_cli.commands.db.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0)
        result = runner.invoke(app, ["db", "migrate", "--path", str(tmp_path)])
    assert result.exit_code == 0
    argv = run.call_args.args[0]
    assert argv[-2:] == ["upgrade", "head"]


def test_db_rollback_default_one_step(tmp_path):
    _project(tmp_path)
    with patch("calango_cli.commands.db.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0)
        runner.invoke(app, ["db", "rollback", "--path", str(tmp_path)])
    assert run.call_args.args[0][-2:] == ["downgrade", "-1"]


def test_db_revision_passes_message(tmp_path):
    _project(tmp_path)
    with patch("calango_cli.commands.db.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0)
        runner.invoke(app, ["db", "revision", "-m", "add orders", "--path", str(tmp_path)])
    argv = run.call_args.args[0]
    assert "--autogenerate" in argv and "add orders" in argv


def test_db_migrate_not_a_project_exits_1(tmp_path):
    result = runner.invoke(app, ["db", "migrate", "--path", str(tmp_path)])
    assert result.exit_code == 1


def test_db_migrate_propagates_alembic_failure(tmp_path):
    _project(tmp_path)
    with patch("calango_cli.commands.db.subprocess.run") as run:
        run.return_value = MagicMock(returncode=1)
        result = runner.invoke(app, ["db", "migrate", "--path", str(tmp_path)])
    assert result.exit_code == 1


def test_discover_seeds_sorts_by_name(tmp_path):
    from calango_cli.commands.db import _discover_seeds

    seeds = tmp_path / "app" / "seeds"
    seeds.mkdir(parents=True)
    (seeds / "__init__.py").write_text("")
    (seeds / "002_b.py").write_text("async def seed(session): ...\n")
    (seeds / "001_a.py").write_text("async def seed(session): ...\n")
    names = [p.name for p in _discover_seeds(tmp_path)]
    assert names == ["001_a.py", "002_b.py"]


def test_db_seed_without_seeds_dir_exits_1(tmp_path):
    (tmp_path / "alembic.ini").write_text("[alembic]\n")
    (tmp_path / "app").mkdir()
    result = runner.invoke(app, ["db", "seed", "--path", str(tmp_path)])
    assert result.exit_code == 1


def test_order_migrations_is_deterministic_and_dependency_first(tmp_path):
    items = (
        PluginMigration("store", tmp_path, ("accounts",)),
        PluginMigration("search", tmp_path, ("catalog",)),
        PluginMigration("accounts", tmp_path, ()),
        PluginMigration("catalog", tmp_path, ()),
    )

    ordered = order_migrations(items)

    assert tuple(item.name for item in ordered) == (
        "accounts",
        "catalog",
        "search",
        "store",
    )


def test_order_migrations_rejects_duplicate_name(tmp_path):
    items = (
        PluginMigration("identity", tmp_path, ()),
        PluginMigration("identity", tmp_path, ()),
    )

    with pytest.raises(MigrationConfigurationError, match=r"duplicate.*identity"):
        order_migrations(items)


def test_order_migrations_rejects_missing_dependency(tmp_path):
    items = (PluginMigration("orders", tmp_path, ("accounts",)),)

    with pytest.raises(MigrationConfigurationError, match=r"orders.*accounts"):
        order_migrations(items)


def test_order_migrations_rejects_cycle(tmp_path):
    items = (
        PluginMigration("accounts", tmp_path, ("orders",)),
        PluginMigration("orders", tmp_path, ("accounts",)),
    )

    with pytest.raises(MigrationConfigurationError, match=r"cycle.*accounts.*orders"):
        order_migrations(items)


def test_version_locations_preserves_topological_order(tmp_path):
    accounts = tmp_path / "accounts"
    orders = tmp_path / "orders"
    accounts.mkdir()
    orders.mkdir()
    items = (
        PluginMigration("orders", orders, ("accounts",)),
        PluginMigration("accounts", accounts, ()),
    )

    assert version_locations(items) == (accounts, orders)


def test_version_locations_rejects_missing_plugin_directory(tmp_path):
    missing = tmp_path / "missing"

    with pytest.raises(MigrationConfigurationError, match=r"identity.*missing"):
        version_locations((PluginMigration("identity", missing, ()),))


def test_version_locations_materializes_non_filesystem_traversable(tmp_path):
    archive_path = tmp_path / "plugin.zip"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr("versions/0001_plugin.py", "revision = 'plugin_0001'\n")

    with ZipFile(archive_path) as archive:
        resource = ZipPath(archive, at="versions/")
        (location,) = version_locations((PluginMigration("plugin", resource, ()),))

    assert location.is_dir()
    assert location.joinpath("0001_plugin.py").read_text() == "revision = 'plugin_0001'\n"


def test_generated_alembic_env_loads_plugins_before_metadata(monkeypatch, tmp_path):
    result = runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])
    assert result.exit_code == 0
    env_path = tmp_path / "my-api" / "alembic" / "env.py"
    events: list[str] = []

    class FakePlugin:
        def migrations(self):
            events.append("migrations")
            versions = tmp_path / "identity-versions"
            versions.mkdir()
            return (PluginMigration("identity", versions, ()),)

    class FakeEntryPoint:
        name = "identity"

        def load(self):
            events.append("plugin-models")
            return FakePlugin

    monkeypatch.setattr(
        "importlib.metadata.entry_points",
        lambda **kwargs: (FakeEntryPoint(),),
    )

    class FakeConfig:
        config_file_name = None
        config_ini_section = "alembic"

        def set_main_option(self, name, value):
            events.append(f"config:{name}:{value}")

        def get_main_option(self, name):
            if name == "version_locations":
                return "alembic/versions"
            return "postgresql+asyncpg://unused"

        def get_section(self, name, default):
            return default

    class Transaction:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    context = ModuleType("alembic.context")
    vars(context).update(
        config=FakeConfig(),
        configure=lambda **kwargs: None,
        begin_transaction=Transaction,
        run_migrations=lambda: None,
        is_offline_mode=lambda: True,
    )
    alembic = ModuleType("alembic")
    vars(alembic)["context"] = context
    monkeypatch.setitem(__import__("sys").modules, "alembic", alembic)
    monkeypatch.setitem(__import__("sys").modules, "alembic.context", context)

    config_module = ModuleType("app.core.config")

    class Settings:
        database = type("Database", (), {"URL": "postgresql+asyncpg://unused"})()

    vars(config_module)["Settings"] = Settings
    monkeypatch.setitem(__import__("sys").modules, "app.core.config", config_module)

    db_module = ModuleType("calango.db")

    class BaseMeta(type):
        @property
        def metadata(cls):
            events.append("metadata")
            return object()

    class Base(metaclass=BaseMeta):
        pass

    def import_models(package):
        events.append(f"models:{package}")

    vars(db_module).update(Base=Base, import_models=import_models)
    monkeypatch.setitem(__import__("sys").modules, "calango.db", db_module)

    code = compile(env_path.read_text(), str(env_path), "exec")
    exec(code, {"__name__": "generated_alembic_env"})

    assert events == [
        "config:sqlalchemy.url:postgresql+asyncpg://unused",
        "plugin-models",
        "migrations",
        "config:version_locations:"
        + os.pathsep.join(("alembic/versions", str(tmp_path / "identity-versions"))),
        "models:app.contexts",
        "metadata",
    ]
