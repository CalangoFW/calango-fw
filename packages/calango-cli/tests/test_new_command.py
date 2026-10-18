import subprocess
import sys
from unittest.mock import patch

import pytest
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


def test_new_creates_tests_conftest(tmp_path):
    """calango new creates tests/conftest.py with db and client fixtures."""
    runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])
    assert (tmp_path / "my-api" / "tests" / "conftest.py").is_file()


def test_new_conftest_has_db_fixture(tmp_path):
    """tests/conftest.py contains the db fixture."""
    runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])
    content = (tmp_path / "my-api" / "tests" / "conftest.py").read_text()
    assert "async def db()" in content


def test_new_conftest_has_client_fixture(tmp_path):
    """tests/conftest.py contains the async client fixture."""
    runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])
    content = (tmp_path / "my-api" / "tests" / "conftest.py").read_text()
    assert "async def client(" in content


def test_new_creates_alembic_env(tmp_path):
    """calango new creates alembic/env.py."""
    runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])
    assert (tmp_path / "my-api" / "alembic" / "env.py").is_file()


def test_new_creates_standard_alembic_revision_template(tmp_path):
    """Generated projects include the template Alembic executes for revisions."""
    runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])

    template = tmp_path / "my-api" / "alembic" / "script.py.mako"

    assert template.is_file()
    content = template.read_text()
    assert "revision: str = ${repr(up_revision)}" in content
    assert "def upgrade() -> None:" in content
    assert "def downgrade() -> None:" in content


def test_new_creates_alembic_ini(tmp_path):
    """calango new creates alembic.ini."""
    runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])
    assert (tmp_path / "my-api" / "alembic.ini").is_file()


def test_new_alembic_ini_has_script_location(tmp_path):
    """alembic.ini has script_location = alembic."""
    runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])
    content = (tmp_path / "my-api" / "alembic.ini").read_text()
    assert "script_location = alembic" in content


def test_new_creates_dockerfile(tmp_path):
    """calango new creates a Dockerfile."""
    runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])
    assert (tmp_path / "my-api" / "Dockerfile").is_file()


def test_new_dockerfile_has_four_stages(tmp_path):
    """Dockerfile has base, development, ci, and production stages."""
    runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])
    content = (tmp_path / "my-api" / "Dockerfile").read_text()
    assert "AS base" in content
    assert "AS development" in content
    assert "AS ci" in content
    assert "AS production" in content


def test_new_creates_compose_yml(tmp_path):
    """calango new creates compose.yml."""
    runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])
    assert (tmp_path / "my-api" / "compose.yml").is_file()


def test_new_compose_has_postgres_service(tmp_path):
    """compose.yml contains postgres service."""
    runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])
    content = (tmp_path / "my-api" / "compose.yml").read_text()
    assert "postgres:" in content


def test_new_compose_has_redis_service(tmp_path):
    """compose.yml contains redis service."""
    runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])
    content = (tmp_path / "my-api" / "compose.yml").read_text()
    assert "redis:" in content


def test_new_compose_has_minio_service(tmp_path):
    """compose.yml contains minio service."""
    runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])
    content = (tmp_path / "my-api" / "compose.yml").read_text()
    assert "minio:" in content


def test_new_compose_postgres_uses_project_name(tmp_path):
    """compose.yml postgres DB uses the project name."""
    runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])
    content = (tmp_path / "my-api" / "compose.yml").read_text()
    assert "my-api" in content


def test_new_creates_ci_yml(tmp_path):
    """calango new creates .github/workflows/ci.yml."""
    runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])
    assert (tmp_path / "my-api" / ".github" / "workflows" / "ci.yml").is_file()


def test_new_ci_yml_has_quality_job(tmp_path):
    """.github/workflows/ci.yml contains quality job."""
    runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])
    content = (tmp_path / "my-api" / ".github" / "workflows" / "ci.yml").read_text()
    assert "quality:" in content


def test_new_ci_yml_has_integration_tests_job(tmp_path):
    """.github/workflows/ci.yml contains test-integration job."""
    runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])
    content = (tmp_path / "my-api" / ".github" / "workflows" / "ci.yml").read_text()
    assert "test-integration:" in content


def test_new_creates_cd_yml(tmp_path):
    """calango new creates .github/workflows/cd.yml."""
    runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])
    assert (tmp_path / "my-api" / ".github" / "workflows" / "cd.yml").is_file()


def test_new_creates_pull_request_template(tmp_path):
    """calango new creates .github/pull_request_template.md."""
    runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])
    assert (tmp_path / "my-api" / ".github" / "pull_request_template.md").is_file()


def test_new_pull_request_template_has_definition_of_done(tmp_path):
    """.github/pull_request_template.md has Definition of Done checklist."""
    runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])
    content = (tmp_path / "my-api" / ".github" / "pull_request_template.md").read_text()
    assert "Definition of Done" in content


def test_new_creates_gitignore(tmp_path):
    """calango new creates .gitignore."""
    runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])
    assert (tmp_path / "my-api" / ".gitignore").is_file()


def test_new_gitignore_ignores_env_file(tmp_path):
    """.gitignore ignores .env file."""
    runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])
    content = (tmp_path / "my-api" / ".gitignore").read_text()
    assert ".env" in content


def test_new_creates_pyproject_toml(tmp_path):
    """calango new creates pyproject.toml."""
    runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])
    assert (tmp_path / "my-api" / "pyproject.toml").is_file()


def test_new_pyproject_installs_cli_runtime_used_by_alembic_env(tmp_path):
    runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])

    content = (tmp_path / "my-api" / "pyproject.toml").read_text()

    assert '"calango-cli>=0.1.0"' in content


def test_new_pyproject_has_calango_dependency(tmp_path):
    """pyproject.toml lists calango-core as a dependency."""
    runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])
    content = (tmp_path / "my-api" / "pyproject.toml").read_text()
    assert "calango-core" in content


def test_new_pyproject_has_coverage_gate(tmp_path):
    """pyproject.toml configures pytest with --cov-fail-under=80."""
    runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])
    content = (tmp_path / "my-api" / "pyproject.toml").read_text()
    assert "--cov-fail-under=80" in content


def test_new_creates_env_example(tmp_path):
    """calango new creates .env.example."""
    runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])
    assert (tmp_path / "my-api" / ".env.example").is_file()


def test_new_env_example_has_secret_key(tmp_path):
    """.env.example includes SECURITY__SECRET_KEY placeholder."""
    runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])
    content = (tmp_path / "my-api" / ".env.example").read_text()
    assert "SECURITY__SECRET_KEY" in content


def test_new_creates_claude_md(tmp_path):
    """calango new creates CLAUDE.md."""
    runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])
    assert (tmp_path / "my-api" / "CLAUDE.md").is_file()


def test_new_claude_md_contains_project_name(tmp_path):
    """CLAUDE.md contains the project name."""
    runner.invoke(app, ["new", "my-cool-api", "--path", str(tmp_path)])
    content = (tmp_path / "my-cool-api" / "CLAUDE.md").read_text()
    assert "my-cool-api" in content


def test_new_creates_cursorrules(tmp_path):
    """calango new creates .cursorrules."""
    runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])
    assert (tmp_path / "my-api" / ".cursorrules").is_file()


def test_new_creates_changelog(tmp_path):
    """calango new creates CHANGELOG.md."""
    runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])
    assert (tmp_path / "my-api" / "CHANGELOG.md").is_file()


def test_new_creates_security_md(tmp_path):
    """calango new creates SECURITY.md."""
    runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])
    assert (tmp_path / "my-api" / "SECURITY.md").is_file()


def test_new_exits_1_for_unsupported_db(tmp_path):
    """calango new exits with code 1 for unsupported --db value."""
    result = runner.invoke(app, ["new", "my-api", "--db", "sqlite", "--path", str(tmp_path)])
    assert result.exit_code == 1


def test_new_exits_1_for_unsupported_ci(tmp_path):
    """calango new exits with code 1 for unsupported --ci value."""
    result = runner.invoke(app, ["new", "my-api", "--ci", "gitlab", "--path", str(tmp_path)])
    assert result.exit_code == 1


def test_new_creates_alembic_versions_gitkeep(tmp_path):
    """calango new creates alembic/versions/.gitkeep."""
    runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])
    assert (tmp_path / "my-api" / "alembic" / "versions" / ".gitkeep").is_file()


def test_calango_no_args_shows_calango_brand():
    """calango with no args prints the calango. banner."""
    result = runner.invoke(app, [])
    assert result.exit_code == 0
    assert "calango" in result.output


def test_new_without_name_in_non_interactive_exits_1(tmp_path):
    """calango new with no name in a non-TTY environment exits 1."""
    result = runner.invoke(app, ["new", "--path", str(tmp_path)])
    assert result.exit_code == 1


def test_new_wizard_creates_project_directory(tmp_path):
    """calango new wizard scaffolds the project when run interactively."""
    with (
        patch("calango_cli.commands.new.is_interactive", return_value=True),
        patch("calango_cli.commands.new.print_banner"),
        patch("calango_cli.commands.new.ask", return_value="wizard-api"),
        patch("calango_cli.commands.new.ask_choice", side_effect=["postgres", "github"]),
        patch("calango_cli.commands.new.ask_confirm", return_value=False),
    ):
        result = runner.invoke(app, ["new", "--path", str(tmp_path)])
    assert result.exit_code == 0
    assert (tmp_path / "wizard-api").is_dir()


def test_new_wizard_project_contains_prompted_name(tmp_path):
    """Wizard-created project uses the name supplied by the prompt."""
    with (
        patch("calango_cli.commands.new.is_interactive", return_value=True),
        patch("calango_cli.commands.new.print_banner"),
        patch("calango_cli.commands.new.ask", return_value="wizard-api"),
        patch("calango_cli.commands.new.ask_choice", side_effect=["postgres", "github"]),
        patch("calango_cli.commands.new.ask_confirm", return_value=False),
    ):
        runner.invoke(app, ["new", "--path", str(tmp_path)])
    content = (tmp_path / "wizard-api" / "app" / "core" / "config.py").read_text()
    assert "wizard-api" in content


def test_new_creates_contexts_dir(tmp_path):
    """calango new creates app/contexts/ directory."""
    runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])
    assert (tmp_path / "my-api" / "app" / "contexts").is_dir()


def test_new_creates_routers_dir(tmp_path):
    """calango new creates app/routers/ directory."""
    runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])
    assert (tmp_path / "my-api" / "app" / "routers").is_dir()


def test_new_creates_opengrep_rules(tmp_path):
    """calango new ships the Calango Opengrep ruleset."""
    runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])
    rules = tmp_path / "my-api" / "security" / "opengrep" / "calango.yml"
    assert rules.exists()
    assert "cl040-raw-sql-string-interpolation" in rules.read_text()


def test_new_pyproject_has_pip_audit(tmp_path):
    """Generated pyproject includes pip-audit as a dev dependency."""
    runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])
    content = (tmp_path / "my-api" / "pyproject.toml").read_text()
    assert "pip-audit" in content


def test_new_ci_has_security_job(tmp_path):
    """Generated CI has a security job running pip-audit and Opengrep."""
    runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])
    ci = (tmp_path / "my-api" / ".github" / "workflows" / "ci.yml").read_text()
    assert "Security (SAST + SCA)" in ci
    assert "pip-audit" in ci
    assert "opengrep" in ci.lower()


def test_new_ci_forces_node24(tmp_path):
    """Generated CI opts every action into Node.js 24 (CLAUDE.md rule)."""
    runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])
    ci = (tmp_path / "my-api" / ".github" / "workflows" / "ci.yml").read_text()
    assert "FORCE_JAVASCRIPT_ACTIONS_TO_NODE24" in ci


def test_new_alembic_env_wires_target_metadata(tmp_path):
    runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])
    env = (tmp_path / "my-api" / "alembic" / "env.py").read_text()
    assert "from calango.db import Base, import_models" in env
    assert "target_metadata = Base.metadata" in env


def test_new_creates_seeds_example(tmp_path):
    runner.invoke(app, ["new", "my-api", "--path", str(tmp_path)])
    example = tmp_path / "my-api" / "app" / "seeds" / "001_example.py"
    assert example.exists()
    assert "async def seed(session" in example.read_text()


def _generate(tmp_path, *options: str):
    result = runner.invoke(app, ["new", "my-api", "--path", str(tmp_path), *options])
    assert result.exit_code == 0, result.output
    return tmp_path / "my-api"


def test_new_env_example_uses_calango_namespace(tmp_path):
    env_example = (_generate(tmp_path) / ".env.example").read_text()
    for name in ("CALANGO_APP_NAME=", "CALANGO_ENV=", "CALANGO_DEBUG="):
        assert name in env_example
    legacy = [line for line in env_example.splitlines() if line.startswith(("APP_NAME=", "ENV="))]
    assert legacy == []


def test_new_without_identity_does_not_install_identity(tmp_path):
    project = _generate(tmp_path)
    assert "identity" not in (project / "app" / "main.py").read_text()
    assert not (project / "app" / "plugins" / "identity.py").exists()
    assert "calango-identity" not in (project / "pyproject.toml").read_text()
    assert "IDENTITY__" not in (project / ".env.example").read_text()


def test_new_with_identity_wires_the_plugin(tmp_path):
    project = _generate(tmp_path, "--identity")
    main = (project / "app" / "main.py").read_text()
    plugin_module = (project / "app" / "plugins" / "identity.py").read_text()
    assert "Calango(settings=settings)" in main
    assert "app.include_plugin(identity_plugin())" in main
    assert "IdentityPlugin" in plugin_module
    assert "IdentityEvents" in plugin_module
    assert "calango-identity" in (project / "pyproject.toml").read_text()
    env_example = (project / ".env.example").read_text()
    for name in ("IDENTITY__PRIVATE_KEY=", "IDENTITY__PUBLIC_KEY=", "IDENTITY__REDIS_URL="):
        assert name in env_example


def test_new_conftest_overrides_framework_session_dependencies(tmp_path):
    conftest = (_generate(tmp_path) / "tests" / "conftest.py").read_text()
    assert "app.core.database" not in conftest
    assert "from calango.core.database import get_db" in conftest
    assert "app.database.session" in conftest


def test_new_identity_conftest_creates_ephemeral_signing_keys(tmp_path):
    conftest = (_generate(tmp_path, "--identity") / "tests" / "conftest.py").read_text()
    assert "IDENTITY__PRIVATE_KEY" in conftest
    assert "generate_private_key" in conftest


@pytest.mark.parametrize("options", [(), ("--identity",)], ids=["default", "identity"])
def test_new_generates_valid_python(tmp_path, options):
    project = _generate(tmp_path, *options)
    for source in (project / "app").rglob("*.py"):
        compile(source.read_text(), str(source), "exec")
    conftest = project / "tests" / "conftest.py"
    compile(conftest.read_text(), str(conftest), "exec")


@pytest.mark.parametrize("options", [(), ("--identity",)], ids=["default", "identity"])
def test_new_project_passes_its_own_ruff_gates(tmp_path, options):
    project = _generate(tmp_path, *options)
    for arguments in (["check", "."], ["format", "--check", "."]):
        result = subprocess.run(
            [sys.executable, "-m", "ruff", *arguments],
            cwd=project,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
