from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from calango_cli.main import app

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
