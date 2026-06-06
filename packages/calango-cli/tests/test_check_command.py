from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from calango_cli.main import app

runner = CliRunner()


def _make_project(tmp_path: Path) -> Path:
    """Create a minimal project marker (pyproject.toml)."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    (tmp_path / "app").mkdir()
    return tmp_path


def test_check_security_help_exits_0():
    """calango check:security --help exits 0."""
    result = runner.invoke(app, ["check:security", "--help"])
    assert result.exit_code == 0


def test_check_security_not_a_project_exits_1(tmp_path):
    """Running outside a Python project exits 1 with a hint."""
    result = runner.invoke(app, ["check:security", "--path", str(tmp_path)])
    assert result.exit_code == 1


def test_check_security_passes_when_both_clean(tmp_path):
    """Exits 0 when both SCA and SAST report no findings."""
    _make_project(tmp_path)
    with (
        patch("calango_cli.commands.check._run_pip_audit", return_value=(True, "clean")),
        patch("calango_cli.commands.check._run_opengrep", return_value=(True, "clean")),
    ):
        result = runner.invoke(app, ["check:security", "--path", str(tmp_path)])
    assert result.exit_code == 0


def test_check_security_fails_on_sca_finding(tmp_path):
    """Exits 1 when pip-audit reports a vulnerability."""
    _make_project(tmp_path)
    with (
        patch("calango_cli.commands.check._run_pip_audit", return_value=(False, "CVE-x")),
        patch("calango_cli.commands.check._run_opengrep", return_value=(True, "clean")),
    ):
        result = runner.invoke(app, ["check:security", "--path", str(tmp_path)])
    assert result.exit_code == 1


def test_check_security_fails_on_sast_finding(tmp_path):
    """Exits 1 when Opengrep reports a finding."""
    _make_project(tmp_path)
    with (
        patch("calango_cli.commands.check._run_pip_audit", return_value=(True, "clean")),
        patch("calango_cli.commands.check._run_opengrep", return_value=(False, "CL040")),
    ):
        result = runner.invoke(app, ["check:security", "--path", str(tmp_path)])
    assert result.exit_code == 1


def test_check_security_runs_both_scanners(tmp_path):
    """Both SCA and SAST scanners are invoked, even if the first passes."""
    _make_project(tmp_path)
    with (
        patch("calango_cli.commands.check._run_pip_audit", return_value=(True, "clean")) as audit,
        patch("calango_cli.commands.check._run_opengrep", return_value=(True, "clean")) as grep,
    ):
        runner.invoke(app, ["check:security", "--path", str(tmp_path)])
    assert audit.called
    assert grep.called
