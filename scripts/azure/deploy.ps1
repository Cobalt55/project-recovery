[CmdletBinding()]
param(
    [switch]$Plan,
    [string]$AzureCli,
    [string]$MetadataPath = (Join-Path $PSScriptRoot "..\..\local-secrets\azure-deployment.json")
)

. (Join-Path $PSScriptRoot "common.ps1")

if ($Plan) {
    Write-Output "Plan: build a tracked deployment artifact, deploy it, restart the Web App, then run a health and login smoke test."
    exit 0
}

$AzureCli = Resolve-ApprovedAzureCli $AzureCli
Assert-ApprovedAzureIdentity $AzureCli
$metadata = Get-DeploymentMetadata $MetadataPath
$repositoryRoot = Get-RepositoryRoot
$artifact = [IO.Path]::ChangeExtension([IO.Path]::GetTempFileName(), ".zip")

try {
    Push-Location $repositoryRoot
    & git diff --quiet
    if ($LASTEXITCODE -ne 0) {
        throw "Refusing to deploy a dirty worktree. Commit or stash application changes first."
    }
    & git archive --format=zip --output=$artifact HEAD
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to build the tracked deployment artifact."
    }
    Invoke-ApprovedAzureCli -AzureCli $AzureCli -Arguments @(
        "webapp", "deploy", "--resource-group", $metadata.resourceGroup, "--name", $metadata.webAppName,
        "--type", "zip", "--src-path", $artifact, "--async", "false", "--output", "none"
    ) | Out-Null
    Invoke-ApprovedAzureCli -AzureCli $AzureCli -Arguments @(
        "webapp", "restart", "--resource-group", $metadata.resourceGroup, "--name", $metadata.webAppName,
        "--output", "none"
    ) | Out-Null
}
finally {
    Pop-Location
    Remove-Item -LiteralPath $artifact -Force -ErrorAction SilentlyContinue
}

& (Join-Path $PSScriptRoot "smoke.ps1") -AzureCli $AzureCli -MetadataPath $MetadataPath
if ($LASTEXITCODE -ne 0) {
    throw "Post-deploy smoke verification failed."
}
Write-Output "Deployment and post-deploy verification completed."
