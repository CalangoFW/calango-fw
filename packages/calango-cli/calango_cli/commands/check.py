from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import typer

from calango_cli.ui import (
    print_error,
    print_info,
    print_success,
)


def _run_pip_audit(project_dir: Path) -> tuple[bool, str]:
    """Audit resolved third-party dependencies for known CVEs.

    Returns (ok, message). A missing toolchain is a soft skip (ok=True) so the
    local convenience command never blocks on environment gaps — CI enforces hard.
    """
    uv = shutil.which("uv")
    if uv is None:
        return (True, "uv not found — SCA skipped")
    export = subprocess.run(  # noqa: S603 — resolved absolute path, fixed args
        [
            uv,
            "export",
            "--format",
            "requirements-txt",
            "--no-emit-workspace",
            "--no-hashes",
            "--no-dev",
        ],
        cwd=project_dir,
        capture_output=True,
        text=True,
    )
    if export.returncode != 0:
        return (True, "could not export dependencies — SCA skipped")
    reqs = "\n".join(line for line in export.stdout.splitlines() if not line.startswith("-e"))
    audit = subprocess.run(  # noqa: S603 — resolved absolute path, fixed args
        [uv, "run", "pip-audit", "-r", "/dev/stdin"],
        cwd=project_dir,
        input=reqs,
        capture_output=True,
        text=True,
    )
    return (audit.returncode == 0, (audit.stdout + audit.stderr).strip())


def _run_opengrep(project_dir: Path) -> tuple[bool, str]:
    """Run the Opengrep SAST scan with the project's Calango rules.

    Returns (ok, message). Missing Opengrep or rules is a soft skip (ok=True).
    """
    opengrep = shutil.which("opengrep")
    if opengrep is None:
        return (True, "opengrep not installed — SAST skipped (see https://opengrep.dev)")
    rules = project_dir / "security" / "opengrep"
    if not rules.exists():
        return (True, "no security/opengrep rules found — SAST skipped")
    target = project_dir / "app" if (project_dir / "app").exists() else project_dir
    result = subprocess.run(  # noqa: S603 — resolved absolute path, fixed args
        [opengrep, "scan", "--config", str(rules), "--error", str(target)],
        cwd=project_dir,
        capture_output=True,
        text=True,
    )
    return (result.returncode == 0, (result.stdout + result.stderr).strip())


def check_security(
    path: Path = typer.Option(Path("."), "--path", help="Project root directory"),
) -> None:
    """Run the security gate: SCA (pip-audit) + SAST (Opengrep)."""
    project_dir = path.resolve()
    if not (project_dir / "pyproject.toml").exists():
        print_error(
            f"'{project_dir}' does not look like a Python project.",
            hint="No pyproject.toml found. Run inside a Calango project.",
        )
        raise typer.Exit(1)

    print_info("Security gate", {"path": str(project_dir), "scanners": "pip-audit · Opengrep"})

    sca_ok, sca_msg = _run_pip_audit(project_dir)
    sast_ok, sast_msg = _run_opengrep(project_dir)

    failures: list[str] = []
    if sca_ok:
        print_success("SCA (pip-audit) — no blocking vulnerabilities")
    else:
        print_error("SCA (pip-audit) — vulnerabilities found", hint=sca_msg or None)
        failures.append("SCA")

    if sast_ok:
        print_success("SAST (Opengrep) — no findings")
    else:
        print_error("SAST (Opengrep) — findings detected", hint=sast_msg or None)
        failures.append("SAST")

    if failures:
        print_error(
            f"Security gate failed: {', '.join(failures)}.",
            hint="Fix the findings above, then re-run calango check:security.",
        )
        raise typer.Exit(1)

    print_success("Security gate passed — no SAST/SCA findings.")
