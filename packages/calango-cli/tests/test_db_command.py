import logging
import os
import subprocess
import sys
from importlib.resources.abc import Traversable
from pathlib import Path
from types import ModuleType
from typing import ClassVar, cast
from unittest.mock import MagicMock, patch
from zipfile import Path as ZipPath
from zipfile import ZipFile

import pytest
from alembic.config import CommandLine, Config
from alembic.script import ScriptDirectory
from calango_plugin_base import PluginMigration
from typer.testing import CliRunner

from calango_cli.main import app
from calango_cli.migrations import (
    MigrationConfigurationError,
    MigrationResources,
    order_migrations,
    version_locations,
)

runner = CliRunner()


class _UnreadableVersions(Traversable):
    @property
    def name(self) -> str:
        return "versions"

    def iterdir(self):
        raise OSError("private resource path")

    def is_dir(self) -> bool:
        return True

    def is_file(self) -> bool:
        return False

    def open(self, mode="r", *args, **kwargs):
        raise OSError("private resource path")


def _project(tmp_path: Path) -> Path:
    (tmp_path / "alembic.ini").write_text("[alembic]\n")
    (tmp_path / "app").mkdir()
    return tmp_path


def _configure_real_alembic_plugin(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    revisions: tuple[str, ...],
) -> Path:
    """Install a subprocess-visible fixture plugin without touching site-packages."""
    versions = project / "fixture_plugin_versions"
    versions.mkdir()
    for index, revision_id in enumerate(revisions):
        (versions / f"{index + 1:04d}_{revision_id}.py").write_text(
            f"revision = {revision_id!r}\n"
            "down_revision = None\n"
            "branch_labels = None\n"
            "depends_on = None\n"
            "def upgrade():\n"
            "    pass\n"
            "def downgrade():\n"
            "    pass\n"
        )
    (project / "fixture_plugin.py").write_text(
        "from pathlib import Path\n"
        "from pydantic_settings import BaseSettings\n"
        "from calango_plugin_base import PluginMigration\n"
        "class FixturePlugin:\n"
        "    name = 'fixture_plugin'\n"
        "    version = '1.0.0'\n"
        "    requires = []\n"
        "    def register(self, app):\n"
        "        pass\n"
        "    def import_models(self):\n"
        "        pass\n"
        "    def migrations(self):\n"
        "        versions = Path(__file__).parent / 'fixture_plugin_versions'\n"
        "        return (PluginMigration('fixture_plugin', versions, ()),)\n"
        "    def settings(self):\n"
        "        return BaseSettings\n"
        "    def test_fixtures(self):\n"
        "        return []\n"
        "    def context_md(self):\n"
        "        return ''\n"
    )
    (project / "sitecustomize.py").write_text(
        "import importlib.metadata\n"
        "class FixtureEntryPoint:\n"
        "    name = 'fixture_plugin'\n"
        "    def load(self):\n"
        "        from fixture_plugin import FixturePlugin\n"
        "        return FixturePlugin\n"
        "def fixture_entry_points(**kwargs):\n"
        "    if kwargs.get('group') == 'calango.plugins':\n"
        "        return (FixtureEntryPoint(),)\n"
        "    return ()\n"
        "importlib.metadata.entry_points = fixture_entry_points\n"
    )
    monkeypatch.setenv("PYTHONPATH", str(project))
    monkeypatch.setenv("SECURITY__SECRET_KEY", "test-only-secret")
    monkeypatch.setenv("DATABASE__URL", "sqlite+aiosqlite:///calango-test.db")
    return versions


def _current_python_alembic_runner(real_run):
    def run(argv, **kwargs):
        assert argv[1:3] == ["run", "alembic"]
        kwargs.pop("capture_output", None)
        kwargs.pop("text", None)
        completed = real_run(
            [sys.executable, "-m", "alembic", *argv[3:]],
            capture_output=True,
            text=True,
            **kwargs,
        )
        sys.stdout.write(completed.stdout)
        sys.stderr.write(completed.stderr)
        return completed

    return run


def _tree_snapshot(root: Path) -> dict[str, bytes | None]:
    return {
        str(path.relative_to(root)): path.read_bytes() if path.is_file() else None
        for path in root.rglob("*")
    }


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


def test_db_revision_real_alembic_uses_generated_template_and_local_destination(
    tmp_path,
    monkeypatch,
):
    result = runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])
    assert result.exit_code == 0
    project = tmp_path / "my-api"
    plugin_versions = _configure_real_alembic_plugin(project, monkeypatch, ("plugin_0001",))
    plugin_before = _tree_snapshot(plugin_versions)
    real_run = subprocess.run

    with (
        patch("calango_cli.commands.db.shutil.which", return_value="/fixture/uv"),
        patch(
            "calango_cli.commands.db.subprocess.run",
            side_effect=_current_python_alembic_runner(real_run),
        ),
    ):
        migrated = runner.invoke(app, ["db", "migrate", "--path", str(project)])
        result = runner.invoke(
            app,
            ["db", "revision", "-m", "add orders", "--path", str(project)],
        )

    assert migrated.exit_code == 0, migrated.output
    assert result.exit_code == 0, result.output
    revisions = tuple((project / "alembic" / "versions").glob("*.py"))
    assert len(revisions) == 1
    content = revisions[0].read_text()
    assert "add orders" in content
    assert "plugin_0001" in content
    assert "def upgrade() -> None:" in content
    assert _tree_snapshot(plugin_versions) == plugin_before


def test_db_revision_requires_head_for_multihead_and_writes_selected_head_locally(
    tmp_path,
    monkeypatch,
):
    result = runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])
    assert result.exit_code == 0
    project = tmp_path / "my-api"
    plugin_versions = _configure_real_alembic_plugin(
        project,
        monkeypatch,
        ("plugin_a_0001", "plugin_b_0001"),
    )
    plugin_before = _tree_snapshot(plugin_versions)
    local_versions = project / "alembic" / "versions"
    real_run = subprocess.run

    with (
        patch("calango_cli.commands.db.shutil.which", return_value="/fixture/uv"),
        patch(
            "calango_cli.commands.db.subprocess.run",
            side_effect=_current_python_alembic_runner(real_run),
        ),
    ):
        migrated = runner.invoke(app, ["db", "migrate", "--path", str(project)])
        ambiguous = runner.invoke(
            app,
            ["db", "revision", "-m", "ambiguous", "--path", str(project)],
        )
        after_ambiguous = tuple(local_versions.glob("*.py"))
        selected = runner.invoke(
            app,
            [
                "db",
                "revision",
                "-m",
                "selected",
                "--head",
                "plugin_a_0001",
                "--path",
                str(project),
            ],
        )

    assert migrated.exit_code == 0, migrated.output
    assert ambiguous.exit_code != 0
    assert "Multiple heads" in ambiguous.output
    assert "--head" in ambiguous.output
    assert "Traceback" not in ambiguous.output
    assert after_ambiguous == ()
    assert selected.exit_code == 0, selected.output
    revisions = tuple(local_versions.glob("*.py"))
    assert len(revisions) == 1
    assert "plugin_a_0001" in revisions[0].read_text()
    assert _tree_snapshot(plugin_versions) == plugin_before


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


@pytest.mark.parametrize(
    "name", ["", ".", "..", "../identity", "identity/plugin", "identity plugin"]
)
def test_order_migrations_rejects_unsafe_plugin_name_without_echoing_it(tmp_path, name):
    descriptor = PluginMigration(name, tmp_path, ())

    with pytest.raises(MigrationConfigurationError, match="invalid plugin migration name") as error:
        order_migrations((descriptor,))

    if "/" in name:
        assert name not in str(error.value)


@pytest.mark.parametrize(
    ("depends_on", "expected"),
    [
        (cast(tuple[str, ...], ["base"]), "must be a tuple"),
        (("",), "invalid dependency"),
        (("../base",), "invalid dependency"),
        (("base", "base"), "duplicate dependency"),
        (("identity",), "cannot depend on itself"),
    ],
)
def test_order_migrations_rejects_invalid_dependency_contract(
    tmp_path,
    depends_on,
    expected,
):
    descriptor = PluginMigration("identity", tmp_path, depends_on)

    with pytest.raises(MigrationConfigurationError, match=expected) as error:
        order_migrations((PluginMigration("base", tmp_path, ()), descriptor))

    assert "identity" in str(error.value)
    assert "Update or reinstall" in str(error.value)


@pytest.mark.parametrize(
    "versions",
    [
        cast(Traversable, object()),
        _UnreadableVersions(),
    ],
)
def test_order_migrations_rejects_non_traversable_or_unreadable_versions(tmp_path, versions):
    descriptor = PluginMigration("identity", versions, ())

    with pytest.raises(MigrationConfigurationError, match=r"identity.*versions") as error:
        order_migrations((descriptor,))

    assert "private resource path" not in str(error.value)
    assert str(tmp_path) not in str(error.value)
    assert "Update or reinstall" in str(error.value)


def test_order_migrations_rejects_file_versions_without_disclosing_path(tmp_path):
    private_file = tmp_path / "customer-private-migrations.py"
    private_file.write_text("revision = 'private'\n")

    with pytest.raises(MigrationConfigurationError, match=r"identity.*versions") as error:
        order_migrations((PluginMigration("identity", private_file, ()),))

    assert str(private_file) not in str(error.value)


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

    with MigrationResources() as resources:
        locations = version_locations(items, resources=resources)

        assert locations[0] != accounts
        assert locations[0].joinpath("0001_accounts.py").is_file()
        assert locations[1].name == "versions"
        assert locations[1] != orders


def test_version_locations_rejects_missing_plugin_directory(tmp_path):
    missing = tmp_path / "missing"

    with (
        MigrationResources() as resources,
        pytest.raises(MigrationConfigurationError, match=r"identity.*versions"),
    ):
        version_locations(
            (PluginMigration("identity", missing, ()),),
            resources=resources,
        )


def test_version_locations_materializes_non_filesystem_traversable(tmp_path):
    archive_path = tmp_path / "plugin.zip"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr("versions/0001_plugin.py", "revision = 'plugin_0001'\n")

    with ZipFile(archive_path) as archive, MigrationResources() as resources:
        resource = ZipPath(archive, at="versions/")
        (location,) = version_locations(
            (PluginMigration("plugin", resource, ()),),
            resources=resources,
        )

        assert location.is_dir()
        assert location.joinpath("0001_plugin.py").read_text() == "revision = 'plugin_0001'\n"
    assert not location.exists()


def test_migration_resources_cleanup_materialized_archives_and_dependency_overlays(tmp_path):
    archive_path = tmp_path / "base-plugin.zip"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr(
            "versions/0001_base.py",
            "revision = 'base_0001'\ndown_revision = None\n",
        )
    dependent = tmp_path / "dependent_versions"
    dependent.mkdir()
    (dependent / "0001_dependent.py").write_text(
        "revision = 'dependent_0001'\ndown_revision = None\n"
    )

    with ZipFile(archive_path) as archive, MigrationResources() as resources:
        base_resource = ZipPath(archive, at="versions/")
        locations = version_locations(
            (
                PluginMigration("base", base_resource, ()),
                PluginMigration("dependent", dependent, ("base",)),
            ),
            resources=resources,
        )
        materialized, overlay = locations
        assert materialized.is_dir()
        assert overlay.is_dir()
        assert overlay != dependent

    assert not materialized.exists()
    assert not overlay.exists()
    assert dependent.is_dir()


def test_owned_version_locations_release_previous_context_on_repeated_use(tmp_path):
    from calango_cli.migrations import (
        own_version_locations,
        release_version_locations,
    )

    archive_path = tmp_path / "plugin.zip"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr(
            "versions/0001_plugin.py",
            "revision = 'plugin_0001'\ndown_revision = None\n",
        )

    config = Config()
    with ZipFile(archive_path) as archive:
        resource = ZipPath(archive, at="versions/")
        first = own_version_locations(
            config,
            (PluginMigration("plugin", resource, ()),),
        )[0]
        assert first.is_dir()

        second = own_version_locations(
            config,
            (PluginMigration("plugin", resource, ()),),
        )[0]
        assert not first.exists()
        assert second.is_dir()

        release_version_locations(config)
        assert not second.exists()


def test_version_locations_wraps_temporary_directory_failure_without_path(
    tmp_path,
):
    archive_path = tmp_path / "plugin.zip"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr(
            "versions/0001_plugin.py",
            "revision = 'plugin_0001'\ndown_revision = None\n",
        )

    with (
        ZipFile(archive_path) as archive,
        MigrationResources() as resources,
        patch(
            "calango_cli.migrations.TemporaryDirectory",
            side_effect=OSError("private /arbitrary/path"),
        ),
        pytest.raises(MigrationConfigurationError, match=r"plugin.*temporary") as error,
    ):
        resource = ZipPath(archive, at="versions/")
        version_locations(
            (PluginMigration("plugin", resource, ()),),
            resources=resources,
        )

    assert "/arbitrary/path" not in str(error.value)
    assert "Update or reinstall" in str(error.value)


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

    with MigrationResources() as resources:
        locations = tuple(reversed(version_locations(items, resources=resources)))
        script_root = tmp_path / "alembic"
        script_root.mkdir()
        config = Config()
        config.set_main_option("script_location", str(script_root))
        config.set_main_option("version_locations", os.pathsep.join(map(str, locations)))
        config.set_main_option("path_separator", "os")
        scripts = ScriptDirectory.from_config(config)

        assert scripts.get_revision("dependent_0001").down_revision == "base_0001"


def test_version_locations_removes_transitively_redundant_parent(tmp_path):
    locations_by_name = {name: tmp_path / f"{name}_versions" for name in ("a", "b", "c")}
    for name, location in locations_by_name.items():
        location.mkdir()
        (location / f"0001_{name}.py").write_text(
            f"revision = '{name}_0001'\n"
            "down_revision = None\n"
            "branch_labels = None\n"
            "depends_on = None\n"
        )
    items = (
        PluginMigration("a", locations_by_name["a"], ()),
        PluginMigration("b", locations_by_name["b"], ("a",)),
        PluginMigration("c", locations_by_name["c"], ("a", "b")),
    )

    with MigrationResources() as resources:
        locations = version_locations(items, resources=resources)
        script_root = tmp_path / "alembic"
        script_root.mkdir()
        config = Config()
        config.set_main_option("script_location", str(script_root))
        config.set_main_option("version_locations", os.pathsep.join(map(str, locations)))
        config.set_main_option("path_separator", "os")
        scripts = ScriptDirectory.from_config(config)

        assert scripts.get_revision("b_0001").down_revision == "a_0001"
        assert scripts.get_revision("c_0001").down_revision == "b_0001"


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

    def own_locations(config, items):
        events.append("migration-resources")
        return tuple(item.versions for item in items)

    monkeypatch.setattr(migrations_module, "own_version_locations", own_locations)

    class FakeConfig:
        config_file_name = None
        config_ini_section = "alembic"
        attributes: ClassVar[dict[str, object]] = {}

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
        "migration-resources",
        "config:version_locations:"
        + os.pathsep.join(("alembic/versions", str(tmp_path / "identity-versions"))),
        "script-graph",
        "models:app.contexts",
        "metadata",
    ]


def test_generated_alembic_env_keeps_existing_loggers_enabled(monkeypatch, tmp_path):
    """In-process migrations must not silence framework, plugin or security logging."""
    result = runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])
    assert result.exit_code == 0
    project = tmp_path / "my-api"
    existing_logger = logging.getLogger("calango.tests.existing_before_migrations")
    monkeypatch.setattr(existing_logger, "disabled", False)
    monkeypatch.setattr("importlib.metadata.entry_points", lambda **kwargs: ())
    monkeypatch.setenv("SECURITY__SECRET_KEY", "test-only-secret")
    monkeypatch.setenv("DATABASE__URL", "sqlite+aiosqlite:///unused.db")
    monkeypatch.chdir(project)

    CommandLine(prog="alembic").main(
        ["-c", str(project / "alembic.ini"), "upgrade", "heads", "--sql"]
    )

    assert existing_logger.disabled is False


def test_generated_alembic_cli_translates_plugin_failure_without_traceback_or_cause(
    monkeypatch,
    tmp_path,
    capsys,
):
    result = runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])
    assert result.exit_code == 0
    project = tmp_path / "my-api"
    private_detail = f"plugin exploded at {tmp_path / 'private-plugin-resource'}"

    class BrokenPlugin:
        name = "broken_plugin"
        version = "1.0.0"
        requires: ClassVar[list[str]] = []

        def register(self, app): ...

        def import_models(self): ...

        def migrations(self):
            raise RuntimeError(private_detail)

        def settings(self): ...

        def test_fixtures(self):
            return []

        def context_md(self):
            return ""

    class BrokenEntryPoint:
        name = "broken_plugin"

        def load(self):
            return BrokenPlugin

    monkeypatch.setattr(
        "importlib.metadata.entry_points",
        lambda **kwargs: (BrokenEntryPoint(),),
    )
    monkeypatch.setenv("SECURITY__SECRET_KEY", "test-only-secret")
    monkeypatch.setenv("DATABASE__URL", "sqlite+aiosqlite:///unused.db")
    monkeypatch.chdir(project)

    with pytest.raises(SystemExit) as exit_info:
        CommandLine(prog="alembic").main(
            ["-c", str(project / "alembic.ini"), "upgrade", "heads", "--sql"]
        )

    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert exit_info.value.code != 0
    assert "broken_plugin" in output
    assert "Update or reinstall" in output
    assert "Traceback" not in output
    assert "RuntimeError" not in output
    assert private_detail not in output
    assert str(tmp_path) not in output
