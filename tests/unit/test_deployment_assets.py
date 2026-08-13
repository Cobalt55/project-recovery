"""Executable guardrails for the production deployment assets."""

from __future__ import annotations

import os
import shutil
import subprocess
import zipfile
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


def test_approved_wrapper_resolves_from_the_git_common_repository(tmp_path: Path) -> None:
    """A linked worktree still uses the approved wrapper stored at the repository root."""

    if POWERSHELL is None:
        pytest.skip("PowerShell is required to validate Azure deployment assets")
    common_dir = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        check=True,
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=15,
    ).stdout.strip()
    expected = (Path(common_dir).parent / "az-amusheno.ps1").resolve()
    completed = subprocess.run(
        [
            POWERSHELL,
            "-NoProfile",
            "-Command",
            f". '{ROOT / 'scripts' / 'azure' / 'common.ps1'}'; Resolve-ApprovedAzureCli",
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=15,
    )

    assert Path(completed.stdout.strip()).resolve() == expected


@pytest.mark.skipif(os.name != "nt", reason="Windows ACL behavior is platform-specific")
def test_deployment_credential_directory_acl_works_from_pwsh(tmp_path: Path) -> None:
    """PowerShell 7 must delegate ACL work to the compatible Windows host."""

    pwsh = shutil.which("pwsh")
    if pwsh is None or shutil.which("powershell.exe") is None:
        pytest.skip("PowerShell 7 and Windows PowerShell are required")
    target = tmp_path / "credentials"
    completed = subprocess.run(
        [
            pwsh,
            "-NoProfile",
            "-Command",
            (
                f". '{ROOT / 'scripts' / 'azure' / 'common.ps1'}'; "
                "Initialize-PrivateCredentialDirectory "
                "-CredentialsPath $env:PROJECT_RECOVERY_TEST_CREDENTIALS"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=ROOT,
        env={
            **os.environ,
            "PROJECT_RECOVERY_TEST_CREDENTIALS": str(target / "bootstrap-credentials.txt"),
        },
        timeout=20,
    )

    assert completed.returncode == 0, completed.stderr
    assert target.is_dir()


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
    assert "BOOTSTRAP_CREDENTIALS_PATH" in completed.stdout
    assert "scripts/bootstrap_users.py" in completed.stdout
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


def test_templates_use_same_origin_static_assets_behind_a_tls_proxy() -> None:
    """Azure proxy headers must not produce HTTP assets in HTTPS pages."""

    templates = ROOT / "src" / "project_recovery" / "templates"
    rendered_sources = "\n".join(
        path.read_text(encoding="utf-8") for path in templates.glob("*.html")
    )

    assert 'href="/static/app.css"' in rendered_sources
    assert 'src="/static/app.js"' in rendered_sources
    assert 'src="/static/knowledge.js"' in rendered_sources
    assert "url_for('static'" not in rendered_sources


def test_oryx_requirements_file_delegates_to_the_pep_621_project() -> None:
    """Oryx recognizes requirements.txt even when dependencies live in pyproject.toml."""

    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    deploy = (ROOT / "scripts" / "azure" / "deploy.ps1").read_text(encoding="utf-8")

    assert requirements.strip() == "."
    assert "git archive" in deploy


def test_deployment_archive_preserves_linux_shell_line_endings() -> None:
    """App Service must receive startup.sh with LF, regardless of local autocrlf settings."""

    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    archive_path = ROOT / ".pytest-git-archive.zip"
    try:
        completed = subprocess.run(
            ["git", "archive", "--format=zip", f"--output={archive_path}", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            cwd=ROOT,
            timeout=15,
        )
        assert completed.stderr == ""
        with zipfile.ZipFile(archive_path) as archive:
            assert b"\r\n" not in archive.read("startup.sh")
    finally:
        archive_path.unlink(missing_ok=True)

    assert "*.sh text eol=lf" in attributes


def test_complete_stack_defaults_to_new_west_us_3_resources() -> None:
    """Prevent accidental reuse of the East US 2 resource group or Key Vault."""

    common = (ROOT / "scripts" / "azure" / "common.ps1").read_text(encoding="utf-8")
    provision = (ROOT / "scripts" / "azure" / "provision.ps1").read_text(encoding="utf-8")
    operations = (ROOT / "docs" / "operations" / "azure-deployment.md").read_text(encoding="utf-8")

    assert '$DefaultLocation = "westus3"' in common
    assert '$DefaultResourceGroup = "project-recovery-westus3-rg"' in common
    assert '[string]$Location = "westus3"' in provision
    assert '[string]$ResourceGroup = "project-recovery-westus3-rg"' in provision
    assert '"keyvault", "create"' in provision
    assert '"--location", $Location' in provision
    assert "recovery-az-key-vault" not in common
    assert "West US 3" in operations
    assert "East US 2" not in operations


def test_provisioning_reuses_the_existing_west_us_3_plan_and_web_app_before_quota() -> None:
    """A stale quota endpoint cannot block the already-provisioned App Service resources."""

    provision = (ROOT / "scripts" / "azure" / "provision.ps1").read_text(encoding="utf-8")

    assert '[string]$AppServicePlanName = "project-recovery-westus3-b3-plan"' in provision
    assert '[string]$WebAppName = "project-recovery-chat-wus3-amush"' in provision
    assert '"appservice", "plan", "list"' in provision
    assert '"webapp", "list"' in provision
    assert '"--sku", "B3"' in provision
    assert '"(?i)linux"' in provision

    quota_probe = "Microsoft.Web/locations/$Location/usages"
    assert quota_probe in provision
    plan_lookup = provision.index('"appservice", "plan", "list"')
    missing_plan_branch = provision.index("if ($null -eq $existingPlan)")
    quota_after_plan_lookup = provision.index("Assert-RegionalAppServiceQuota", missing_plan_branch)
    assert plan_lookup < missing_plan_branch < quota_after_plan_lookup
    assert provision.index('"webapp", "list"') < provision.index('"webapp", "create"')
    assert "appServicePlanName = $AppServicePlanName" in provision
    assert "webAppName = $WebAppName" in provision


def test_provisioning_validates_the_actual_web_app_plan_runtime_and_resume_state() -> None:
    """Retrying after a partial provision must preserve the validated production topology."""

    provision = (ROOT / "scripts" / "azure" / "provision.ps1").read_text(encoding="utf-8")

    assert '[string]$KeyVaultName = "project-recovery-kv-wus3"' in provision
    assert '[string]$PostgresServerName = "project-recovery-pg-wus3-amush"' in provision
    assert "appServicePlanId:appServicePlanId" in provision
    assert "$existingWebApp.appServicePlanId -ine $existingPlan.id" in provision
    assert '"webapp", "config", "show"' in provision
    assert '"PYTHON|3.12"' in provision
    assert provision.index('"webapp", "list"') < provision.index('"keyvault", "create"')
    assert 'provisioningState = "in-progress"' in provision
    assert 'provisioningState = "complete"' in provision
    assert '"postgres", "flexible-server", "list"' in provision
    assert '"postgres", "flexible-server", "update"' in provision
    assert (
        "@${PostgresServerName}.postgres.database.azure.com:5432/${databaseName}?ssl=require"
        in provision
    )


def test_configuration_uses_generic_health_config_and_idempotent_identity_role() -> None:
    """The installed Azure CLI accepts health path only through generic configuration."""

    configure = (ROOT / "scripts" / "azure" / "configure.ps1").read_text(encoding="utf-8")

    assert '"--generic-configurations", "@$healthConfigPath"' in configure
    assert 'healthCheckPath = "/health/ready"' in configure
    assert "Remove-Item -LiteralPath $healthConfigPath" in configure
    assert '"--settings", "@$appSettingsPath"' in configure
    assert "Remove-Item -LiteralPath $appSettingsPath" in configure
    assert "$appSettings | ConvertTo-Json" in configure
    assert '"role", "assignment", "list"' in configure
    assert 'if ($keyVaultSecretsUserAssignmentCount -eq "0")' in configure
    assert '"--health-check-path"' not in configure


def test_deployment_bootstrap_handoff_is_private_idempotent_and_self_contained() -> None:
    """Deployment retrieves bootstrap credentials once and removes the remote plaintext."""

    configure = (ROOT / "scripts" / "azure" / "configure.ps1").read_text(encoding="utf-8")
    deploy = (ROOT / "scripts" / "azure" / "deploy.ps1").read_text(encoding="utf-8")
    operations = (ROOT / "docs" / "operations" / "azure-deployment.md").read_text(encoding="utf-8")

    assert 'BOOTSTRAP_CREDENTIALS_PATH = "/home/data/bootstrap-credentials.txt"' in configure
    assert '"webapp", "deployment", "list-publishing-credentials"' in deploy
    assert "scm.azurewebsites.net/api/vfs/data/bootstrap-credentials.txt" in deploy
    assert "$client.DeleteAsync($remoteUri).GetAwaiter().GetResult()" in deploy
    assert "if (-not (Test-Path -LiteralPath $CredentialsPath -PathType Leaf))" in deploy
    assert "bootstrap-credentials.txt" in operations


def test_smoke_check_recovers_expected_no_redirect_responses() -> None:
    """PowerShell 7 can throw for a deliberate 303 despite SkipHttpErrorCheck."""

    smoke = (ROOT / "scripts" / "azure" / "smoke.ps1").read_text(encoding="utf-8")

    assert "function Invoke-NoRedirectWebRequest" in smoke
    assert "System.Net.Http.HttpClientHandler" in smoke
    assert "AllowAutoRedirect = $false" in smoke
    assert "System.Net.Http.FormUrlEncodedContent" in smoke
    assert "GetAwaiter().GetResult()" in smoke
    assert "$null -ne $response.Headers.Location" in smoke
    assert "$location = if" in smoke
    assert "$client.Dispose()" in smoke
    assert "$handler.Dispose()" in smoke
    assert "Invoke-NoRedirectWebRequest -Uri" in smoke
    assert "-SessionVariable" not in smoke


def test_app_service_plan_uses_the_requested_location_explicitly() -> None:
    """The plan must not silently inherit a differently located resource group."""

    provision = (ROOT / "scripts" / "azure" / "provision.ps1").read_text(encoding="utf-8")
    plan_create = provision.split('"appservice", "plan", "create"', maxsplit=1)[1]
    plan_create = plan_create.split(") | Out-Null", maxsplit=1)[0]

    assert '"--location", $Location' in plan_create
