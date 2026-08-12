[CmdletBinding()]
param(
    [switch]$Plan,
    [string]$AzureCli,
    [string]$MetadataPath = (Join-Path $PSScriptRoot "..\..\local-secrets\azure-deployment.json"),
    [string]$CredentialsPath = (Join-Path $PSScriptRoot "..\..\local-secrets\bootstrap-credentials.txt")
)

. (Join-Path $PSScriptRoot "common.ps1")

if ($Plan) {
    Write-Output "Plan: run a health and login smoke test without printing credentials or secret values."
    exit 0
}

$AzureCli = Resolve-ApprovedAzureCli $AzureCli
Assert-ApprovedAzureIdentity $AzureCli
$metadata = Get-DeploymentMetadata $MetadataPath
$hostname = Get-WebAppHostName -AzureCli $AzureCli -ResourceGroup $metadata.resourceGroup -WebAppName $metadata.webAppName
$baseUri = "https://$hostname"

foreach ($path in @("/health/live", "/health/ready")) {
    $response = Invoke-WebRequest -Uri "$baseUri$path" -MaximumRedirection 0 -SkipHttpErrorCheck
    if ($response.StatusCode -ne 200) {
        throw "Production health check failed for $path."
    }
}

if (-not (Test-Path -LiteralPath $CredentialsPath -PathType Leaf)) {
    throw "Bootstrap credentials are required for the authenticated login smoke test."
}
$credentialLine = Get-Content -LiteralPath $CredentialsPath | Where-Object { $_ -match '^[^\s:]+@[^\s:]+:\s+.+$' } | Select-Object -First 1
if ([string]::IsNullOrWhiteSpace($credentialLine)) {
    throw "Bootstrap credentials do not have the expected local handoff format."
}
$email, $password = $credentialLine -split ':\s+', 2
$login = Invoke-WebRequest -Uri "$baseUri/login" -Method Post -Body @{ email = $email; password = $password } -MaximumRedirection 0 -SkipHttpErrorCheck -SessionVariable session
if ($login.StatusCode -ne 303 -or $login.Headers.Location -notmatch '^/password/change$') {
    throw "Production login did not require the initial password change."
}
Write-Output "Production health and forced-password-change login smoke test passed."
