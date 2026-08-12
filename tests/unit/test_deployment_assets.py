"""Executable guardrails for the production deployment assets."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")


def _run_plan(script_name: str) -> str:
    """Run an Azure script's non-mutating plan mode and return safe output."""

    if POWERSHELL is None:
        pytest.skip("PowerShell is required to validate Azure deployment assets")
    completed = subprocess.run(
        [POWERSHELL, "-NoProfile", "-File", str(ROOT / "scripts" / "azure" / script_name), "-Plan"],
        check=True,
        capture_output=True,
        text=True,
        cwd=ROOT,
        env={**os.environ, "OPENAI_API_KEY": "must-not-appear-in-output"},
        timeout=15,
    )
    return completed.stdout


@pytest.mark.parametrize(
    ("script_name", "expected"),
    [
        ("provision.ps1", "Basic B3 Linux App Service"),
        ("configure.ps1", "Key Vault references"),
        ("deploy.ps1", "tracked deployment artifact"),
        ("smoke.ps1", "health and login smoke test"),
    ],
)
def test_azure_scripts_offer_a_non_mutating_deployment_plan(
    script_name: str, expected: str
) -> None:
    """Catch a removed safe inspection mode before anyone runs a mutation."""

    output = _run_plan(script_name)

    assert expected in output
    assert "must-not-appear-in-output" not in output


def test_startup_validation_confirms_migrations_precede_the_server() -> None:
    """Catch a startup sequence that could serve requests before schema upgrade."""

    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is required to validate the Linux startup command")

    completed = subprocess.run(
        [bash, "startup.sh", "--validate"],
        check=True,
        capture_output=True,
        text=True,
        cwd=ROOT,
        env=os.environ.copy(),
        timeout=15,
    )

    assert "alembic upgrade head" in completed.stdout
    assert "uvicorn project_recovery.app:create_app" in completed.stdout


def test_workflows_use_oidc_and_the_deployment_workflow_checks_health() -> None:
    """Catch a workflow regression to static credentials or blind deployment."""

    deploy = (ROOT / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")
    tests = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")

    assert "id-token: write" in deploy
    assert "azure/login@v2" in deploy
    assert "health/ready" in deploy
    assert "pytest" in tests
    assert "ruff check" in tests
    assert "mypy src" in tests


def test_deployment_uses_private_postgres_networking_and_packages_web_assets() -> None:
    """Production cannot depend on a public database or omit templates from its wheel."""
    provision = (ROOT / "scripts" / "azure" / "provision.ps1").read_text(encoding="utf-8")
    configure = (ROOT / "scripts" / "azure" / "configure.ps1").read_text(encoding="utf-8")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert "--vnet" in provision
    assert "--subnet" in provision
    assert "--private-dns-zone" in provision
    assert "--public-access" not in provision
    assert "vnet-integration" in configure
    assert '"group", "exists"' in provision
    assert "templates/*.html" in pyproject
    assert "static/*" in pyproject
