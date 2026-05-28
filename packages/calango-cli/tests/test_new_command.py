from typer.testing import CliRunner

from calango_cli.main import app

runner = CliRunner()


def test_calango_version_flag():
    """--version returns version string."""
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "calango" in result.output
    assert "0.1.0-dev" in result.output


def test_calango_help_shows_new_command():
    """calango --help shows 'new' command."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "new" in result.output


def test_new_creates_project_directory(tmp_path):
    """calango new my-api creates directory at tmp_path/my-api."""
    runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])
    assert (tmp_path / "my-api").is_dir()


def test_new_exits_0_on_success(tmp_path):
    """calango new exits with code 0 on success."""
    result = runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])
    assert result.exit_code == 0


def test_new_exits_1_if_directory_exists(tmp_path):
    """calango new exits with code 1 if directory already exists."""
    (tmp_path / "my-api").mkdir()
    result = runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])
    assert result.exit_code == 1


def test_new_accepts_path_option(tmp_path):
    """calango new my-api --path /tmp creates at /tmp/my-api."""
    result = runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])
    assert result.exit_code == 0
    assert (tmp_path / "my-api").is_dir()


def test_new_default_options_are_valid(tmp_path):
    """calango new works without any optional flags."""
    result = runner.invoke(app, ["new", "simple-project", "--path", str(tmp_path)])
    assert result.exit_code == 0
    assert (tmp_path / "simple-project").is_dir()
