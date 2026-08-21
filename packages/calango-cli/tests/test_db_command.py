import os
from pathlib import Path
from types import ModuleType
from typing import ClassVar
from unittest.mock import MagicMock, patch
from zipfile import Path as ZipPath
from zipfile import ZipFile

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
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


def test_db_migrate_runs_upgrade_all_heads(tmp_path):
    _project(tmp_path)
    with patch("calango_cli.commands.db.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0)
        result = runner.invoke(app, ["db", "migrate", "--path", str(tmp_path)])
    assert result.exit_code == 0
    argv = run.call_args.args[0]
    assert argv[-2:] == ["upgrade", "heads"]


def test_db_rollback_default_one_step_on_every_current_head(tmp_path):
    _project(tmp_path)
    with patch("calango_cli.commands.db.subprocess.run") as run:
        run.side_effect = (
            MagicMock(
                returncode=0,
                stdout="Rev: z_head (head) (current)\nRev: a_head (head) (current)\n",
            ),
            MagicMock(returncode=0),
            MagicMock(returncode=0),
        )
        result = runner.invoke(app, ["db", "rollback", "--path", str(tmp_path)])

    assert result.exit_code == 0
    assert [call.args[0][-2:] for call in run.call_args_list] == [
        ["current", "--verbose"],
        ["downgrade", "a_head@-1"],
        ["downgrade", "z_head@-1"],
    ]


def test_db_rollback_applies_step_to_every_current_head(tmp_path):
    _project(tmp_path)
    with patch("calango_cli.commands.db.subprocess.run") as run:
        run.side_effect = (
            MagicMock(
                returncode=0,
                stdout=("Rev: orders_0002 (head) (current)\nRev: identity_0001 (head) (current)\n"),
            ),
            MagicMock(returncode=0),
            MagicMock(returncode=0),
            MagicMock(
                returncode=0,
                stdout=("Rev: orders_0001 (head) (current)\nRev: identity_base (head) (current)\n"),
            ),
            MagicMock(returncode=0),
            MagicMock(returncode=0),
        )
        result = runner.invoke(
            app,
            ["db", "rollback", "--step", "2", "--path", str(tmp_path)],
        )

    assert result.exit_code == 0
    assert [call.args[0][-2:] for call in run.call_args_list] == [
        ["current", "--verbose"],
        ["downgrade", "identity_0001@-1"],
        ["downgrade", "orders_0002@-1"],
        ["current", "--verbose"],
        ["downgrade", "identity_base@-1"],
        ["downgrade", "orders_0001@-1"],
    ]


def test_db_rollback_rejects_non_positive_step_without_running_alembic(tmp_path):
    _project(tmp_path)
    with patch("calango_cli.commands.db.subprocess.run") as run:
        result = runner.invoke(
            app,
            ["db", "rollback", "--step", "0", "--path", str(tmp_path)],
        )

    assert result.exit_code != 0
    run.assert_not_called()


def test_db_rollback_uses_explicit_parent_for_merge_revision(tmp_path):
    _project(tmp_path)
    current = (
        "Current revision(s) for postgresql://localhost/db:\n"
        "Rev: merge_head (head) (mergepoint) (current)\n"
        "Merges: z_parent, a_parent\n"
        "Path: /tmp/merge.py\n"
    )
    with patch("calango_cli.commands.db.subprocess.run") as run:
        run.side_effect = (
            MagicMock(returncode=0, stdout=current),
            MagicMock(returncode=0),
        )
        result = runner.invoke(app, ["db", "rollback", "--path", str(tmp_path)])

    assert result.exit_code == 0
    assert [call.args[0][-2:] for call in run.call_args_list] == [
        ["current", "--verbose"],
        ["downgrade", "merge_head@a_parent"],
    ]


def test_db_rollback_rechecks_graph_before_crossing_merge(tmp_path):
    _project(tmp_path)
    child = "Rev: child (head) (current)\nParent: merge_head\n"
    merge = "Rev: merge_head (head) (mergepoint) (current)\nMerges: z_parent, a_parent\n"
    with patch("calango_cli.commands.db.subprocess.run") as run:
        run.side_effect = (
            MagicMock(returncode=0, stdout=child),
            MagicMock(returncode=0),
            MagicMock(returncode=0, stdout=merge),
            MagicMock(returncode=0),
        )
        result = runner.invoke(
            app,
            ["db", "rollback", "--step", "2", "--path", str(tmp_path)],
        )

    assert result.exit_code == 0
    assert [call.args[0][-2:] for call in run.call_args_list] == [
        ["current", "--verbose"],
        ["downgrade", "child@-1"],
        ["current", "--verbose"],
        ["downgrade", "merge_head@a_parent"],
    ]


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
    (accounts / "0001_accounts.py").write_text("revision = 'accounts_0001'\ndown_revision = None\n")
    (orders / "0001_orders.py").write_text("revision = 'orders_0001'\ndown_revision = None\n")
    items = (
        PluginMigration("orders", orders, ("accounts",)),
        PluginMigration("accounts", accounts, ()),
    )

    locations = version_locations(items)

    assert locations[0] == accounts
    assert locations[1].name == orders.name
    assert locations[1] != orders


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


def test_version_locations_adds_effective_alembic_dependency_edges(tmp_path):
    base_versions = tmp_path / "base_versions"
    dependent_versions = tmp_path / "dependent_versions"
    base_versions.mkdir()
    dependent_versions.mkdir()
    (base_versions / "0001_base.py").write_text(
        "revision = 'base_0001'\ndown_revision = None\nbranch_labels = None\ndepends_on = None\n"
    )
    (dependent_versions / "0001_dependent.py").write_text(
        "revision = 'dependent_0001'\n"
        "down_revision = None\n"
        "branch_labels = None\n"
        "depends_on = None\n"
    )
    items = (
        PluginMigration("dependent", dependent_versions, ("base",)),
        PluginMigration("base", base_versions, ()),
    )

    locations = tuple(reversed(version_locations(items)))
    script_root = tmp_path / "alembic"
    script_root.mkdir()
    config = Config()
    config.set_main_option("script_location", str(script_root))
    config.set_main_option("version_locations", os.pathsep.join(map(str, locations)))
    config.set_main_option("path_separator", "os")
    scripts = ScriptDirectory.from_config(config)

    assert scripts.get_revision("dependent_0001").down_revision == "base_0001"


def test_generated_alembic_env_loads_plugins_before_metadata(monkeypatch, tmp_path):
    import calango_cli.migrations as migrations_module

    result = runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])
    assert result.exit_code == 0
    env_path = tmp_path / "my-api" / "alembic" / "env.py"
    events: list[str] = []

    class FakePlugin:
        name = "identity"
        version = "1.0.0"
        requires: ClassVar[list[str]] = []

        def register(self, app): ...

        def import_models(self):
            events.append("plugin-models")

        def migrations(self):
            events.append("migrations")
            versions = tmp_path / "identity-versions"
            versions.mkdir()
            return (PluginMigration("identity", versions, ()),)

        def settings(self): ...

        def test_fixtures(self):
            return []

        def context_md(self):
            return ""

    class FakeEntryPoint:
        name = "identity"

        def load(self):
            events.append("entry-point")
            return FakePlugin

    monkeypatch.setattr(
        "importlib.metadata.entry_points",
        lambda **kwargs: (FakeEntryPoint(),),
    )
    monkeypatch.setattr(
        migrations_module,
        "refresh_alembic_script",
        lambda config, script: events.append("script-graph"),
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
        script=object(),
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
        "entry-point",
        "plugin-models",
        "migrations",
        "config:version_locations:"
        + os.pathsep.join(("alembic/versions", str(tmp_path / "identity-versions"))),
        "script-graph",
        "models:app.contexts",
        "metadata",
    ]
