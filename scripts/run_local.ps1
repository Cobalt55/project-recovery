<#
.SYNOPSIS
    Run the Project Recovery app locally without echoing configuration secrets.

.DESCRIPTION
    The app reads required OPENAI_* and DATABASE_URL values from .env/.env.local
    or the current process environment. This helper only validates that the
    variable names are present, runs migrations, and starts Uvicorn in the
    foreground. It never prints secret values.
#>
[CmdletBinding()]
param(
    [int]$Port = 8000,
    [switch]$SkipMigrations,
    [switch]$BootstrapAdmins
)

$ErrorActionPreference = "Stop"
$repository = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location -LiteralPath $repository

$requiredVariables = @(
    "OPENAI_API_KEY",
    "OPENAI_VECTOR_STORE_ID",
    "DATABASE_URL",
    "APP_SESSION_SECRET",
    "CHAINLIT_AUTH_SECRET"
)
foreach ($variableName in $requiredVariables) {
    $value = [Environment]::GetEnvironmentVariable($variableName)
    if ([string]::IsNullOrWhiteSpace($value)) {
        throw "Required configuration variable is missing: $variableName"
    }
}

$env:PYTHONPATH = Join-Path $repository "src"
if ([string]::IsNullOrWhiteSpace($env:ATTACHMENT_STORAGE_PATH)) {
    $env:ATTACHMENT_STORAGE_PATH = Join-Path $repository ".test-data\uploads"
}
New-Item -ItemType Directory -Force -Path $env:ATTACHMENT_STORAGE_PATH | Out-Null

if (-not $SkipMigrations) {
    & python -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) {
        throw "Database migrations failed with exit code $LASTEXITCODE"
    }
}

if ($BootstrapAdmins) {
    & python scripts/bootstrap_users.py
    if ($LASTEXITCODE -ne 0) {
        throw "Administrator bootstrap failed with exit code $LASTEXITCODE"
    }
}

& python -m uvicorn project_recovery.app:create_app --factory --host 127.0.0.1 --port $Port
exit $LASTEXITCODE

