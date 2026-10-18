"""A generated Identity project, end to end: scaffold, migrate, serve, sign in."""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from typer.testing import CliRunner

from calango_cli.main import app as cli

pytestmark = pytest.mark.integration

PASSWORD = "SecurePassword123!"
_HOST_SETTING_PREFIXES = (
    "CALANGO_",
    "DATABASE__",
    "REDIS__",
    "SECURITY__",
    "IDENTITY__",
    "PYTEST_",
)
_LEGACY_HOST_SETTINGS = {"APP_NAME", "VERSION", "ENV", "DEBUG"}

GENERATED_TESTS = """\
CREDENTIALS = {"email": "isolated@example.com", "password": "SecurePassword123!"}


async def test_registered_user_reads_own_account(client):
    registered = await client.post("/auth/register", json=CREDENTIALS)
    assert registered.status_code == 201, registered.text
    login = await client.post(
        "/auth/login",
        data={"username": CREDENTIALS["email"], "password": CREDENTIALS["password"]},
    )
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    me = await client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200, me.text


async def test_each_test_starts_from_a_clean_database(client):
    registered = await client.post("/auth/register", json=CREDENTIALS)
    assert registered.status_code == 201, registered.text
"""


def _escaped_pem(pem: bytes) -> str:
    return pem.decode().replace("\n", "\\n")


def _signing_keys() -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return _escaped_pem(private), _escaped_pem(public)


def _scaffold(tmp_path: Path, postgres_url: str, redis_url: str) -> Path:
    result = CliRunner().invoke(cli, ["new", "shop", "--path", str(tmp_path), "--identity"])
    assert result.exit_code == 0, result.output
    project = tmp_path / "shop"
    private_key, public_key = _signing_keys()
    (project / ".env").write_text(
        "CALANGO_ENV=development\n"
        "SECURITY__SECRET_KEY=generated-project-e2e-secret\n"
        f"DATABASE__URL={postgres_url}\n"
        f"REDIS__URL={redis_url}\n"
        f'IDENTITY__PRIVATE_KEY="{private_key}"\n'
        f'IDENTITY__PUBLIC_KEY="{public_key}"\n'
        f"IDENTITY__REDIS_URL={redis_url}\n"
    )
    return project


def _project_env() -> dict[str, str]:
    """The host environment minus settings that would override the project's .env."""
    return {
        name: value
        for name, value in os.environ.items()
        if not name.startswith(_HOST_SETTING_PREFIXES) and name not in _LEGACY_HOST_SETTINGS
    }


def _run_sync(project: Path, arguments: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *arguments],
        cwd=project,
        env=_project_env(),
        capture_output=True,
        text=True,
        check=False,
    )


async def _run(project: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return await asyncio.to_thread(_run_sync, project, arguments)


async def _migrate(project: Path) -> None:
    result = await _run(project, "-m", "alembic", "upgrade", "heads")
    assert result.returncode == 0, result.stdout + result.stderr


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


async def _wait_until_serving(client: httpx.AsyncClient, server: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if server.poll() is not None:
            output = server.stdout.read() if server.stdout else ""
            pytest.fail(f"generated app exited early:\n{output}")
        try:
            await client.get("/")
        except httpx.TransportError:
            await asyncio.sleep(0.2)
        else:
            return
    pytest.fail("generated app did not start serving within 30 seconds")


async def test_generated_identity_app_serves_a_full_session(tmp_path, postgres_url, redis_url):
    project = _scaffold(tmp_path, postgres_url, redis_url)
    await _migrate(project)
    port = _free_port()
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=project,
        env=_project_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
            await _wait_until_serving(client, server)

            registered = await client.post(
                "/auth/register", json={"email": "owner@example.com", "password": PASSWORD}
            )
            assert registered.status_code == 201, registered.text

            login = await client.post(
                "/auth/login", data={"username": "owner@example.com", "password": PASSWORD}
            )
            assert login.status_code == 200, login.text
            assert login.headers["cache-control"] == "no-store"
            tokens = login.json()
            headers = {"Authorization": f"Bearer {tokens['access_token']}"}

            assert (await client.get("/users/me")).status_code == 401
            me = await client.get("/users/me", headers=headers)
            assert me.status_code == 200, me.text
            assert me.json()["email"] == "owner@example.com"

            rotated = await client.post(
                "/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
            )
            assert rotated.status_code == 200, rotated.text
            refresh_token = rotated.json()["refresh_token"]

            logout = await client.post("/auth/logout", json={"refresh_token": refresh_token})
            assert logout.status_code == 204
            after_logout = await client.post("/auth/refresh", json={"refresh_token": refresh_token})
            assert after_logout.status_code == 401
    finally:
        server.terminate()
        server.wait(timeout=10)
        if server.stdout:
            server.stdout.close()


async def test_generated_identity_project_test_suite_passes(tmp_path, postgres_url, redis_url):
    project = _scaffold(tmp_path, postgres_url, redis_url)
    await _migrate(project)
    (project / "tests" / "test_identity_session.py").write_text(GENERATED_TESTS)

    result = await _run(
        project,
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        # Coverage gates belong to real projects; the scaffold alone has no code to cover.
        "-o",
        "addopts=--import-mode=importlib",
        "tests",
    )

    assert result.returncode == 0, result.stdout + result.stderr
