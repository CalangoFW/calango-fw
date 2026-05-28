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


def test_new_creates_app_init(tmp_path):
    """calango new creates app/__init__.py."""
    runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])
    assert (tmp_path / "my-api" / "app" / "__init__.py").is_file()


def test_new_creates_app_main(tmp_path):
    """calango new creates app/main.py with Calango import."""
    runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])
    content = (tmp_path / "my-api" / "app" / "main.py").read_text()
    assert "from calango import Calango" in content


def test_new_creates_app_core_config(tmp_path):
    """calango new creates app/core/config.py with Settings class."""
    runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])
    assert (tmp_path / "my-api" / "app" / "core" / "config.py").is_file()
    content = (tmp_path / "my-api" / "app" / "core" / "config.py").read_text()
    assert "class Settings(CalangoSettings)" in content


def test_new_config_contains_project_name(tmp_path):
    """app/core/config.py contains the project name in APP_NAME."""
    runner.invoke(app, ["new", "my-cool-api", "--path", str(tmp_path)])
    content = (tmp_path / "my-cool-api" / "app" / "core" / "config.py").read_text()
    assert "my-cool-api" in content


def test_new_creates_tests_init(tmp_path):
    """calango new creates tests/__init__.py."""
    runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])
    assert (tmp_path / "my-api" / "tests" / "__init__.py").is_file()
