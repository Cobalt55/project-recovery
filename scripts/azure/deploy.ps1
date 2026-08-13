[CmdletBinding()]
param(
    [switch]$Plan,
    [string]$AzureCli,
    [string]$MetadataPath = (Join-Path $PSScriptRoot "..\..\local-secrets\azure-deployment.json"),
    [string]$CredentialsPath = (Join-Path $PSScriptRoot "..\..\local-secrets\bootstrap-credentials.txt")
)

. (Join-Path $PSScriptRoot "common.ps1")

function Receive-BootstrapCredentials {
    param(
        [Parameter(Mandatory)][string]$AzureCli,
        [Parameter(Mandatory)][object]$Metadata,
        [Parameter(Mandatory)][string]$CredentialsPath
    )

    $publishingJson = Invoke-ApprovedAzureCli -AzureCli $AzureCli -Arguments @(
        "webapp", "deployment", "list-publishing-credentials", "--resource-group", $Metadata.resourceGroup,
        "--name", $Metadata.webAppName, "--output", "json"
    )
    $publishing = $publishingJson | Out-String | ConvertFrom-Json
    if ([string]::IsNullOrWhiteSpace($publishing.publishingUserName) -or
        [string]::IsNullOrWhiteSpace($publishing.publishingPassword)) {
        throw "Unable to obtain publishing credentials for the bootstrap handoff."
    }
    $credentialBytes = [Text.Encoding]::UTF8.GetBytes(
        "$($publishing.publishingUserName):$($publishing.publishingPassword)"
    )
    $credentialToken = [Convert]::ToBase64String($credentialBytes)
    $remoteUri = "https://$($Metadata.webAppName).scm.azurewebsites.net/api/vfs/data/bootstrap-credentials.txt"
    Initialize-PrivateCredentialDirectory -CredentialsPath $CredentialsPath
    $temporaryPath = Join-Path (Split-Path -Parent $CredentialsPath) ".bootstrap-$([guid]::NewGuid().ToString('N')).tmp"
    $handler = [System.Net.Http.HttpClientHandler]::new()
    $client = [System.Net.Http.HttpClient]::new($handler)
    $client.DefaultRequestHeaders.Authorization = [System.Net.Http.Headers.AuthenticationHeaderValue]::new("Basic", $credentialToken)
    try {
        if (-not (Test-Path -LiteralPath $CredentialsPath -PathType Leaf)) {
            $downloaded = $false
            foreach ($attempt in 1..12) {
                $response = $client.GetAsync($remoteUri).GetAwaiter().GetResult()
                try {
                    if ($response.IsSuccessStatusCode) {
                        $contents = $response.Content.ReadAsByteArrayAsync().GetAwaiter().GetResult()
                        if ($contents.Length -eq 0) {
                            throw "Bootstrap credential handoff was empty."
                        }
                        [System.IO.File]::WriteAllBytes($temporaryPath, $contents)
                        Move-Item -LiteralPath $temporaryPath -Destination $CredentialsPath -ErrorAction Stop
                        $downloaded = $true
                        break
                    }
                    if ([int]$response.StatusCode -ne 404) {
                        throw "Bootstrap credential handoff could not be downloaded."
                    }
                }
                finally {
                    $response.Dispose()
                }
                Start-Sleep -Seconds 5
            }
            if (-not $downloaded) {
                throw "Bootstrap credential handoff was not created before deployment verification."
            }
        }
        $deleteResponse = $client.DeleteAsync($remoteUri).GetAwaiter().GetResult()
        try {
            if (-not $deleteResponse.IsSuccessStatusCode -and [int]$deleteResponse.StatusCode -ne 404) {
                throw "Bootstrap credential handoff could not be removed from the Web App."
            }
        }
        finally {
            $deleteResponse.Dispose()
        }
    }
    finally {
        Remove-Item -LiteralPath $temporaryPath -Force -ErrorAction SilentlyContinue
        $client.Dispose()
        $handler.Dispose()
        $credentialBytes = $null
        $credentialToken = $null
    }
}

if ($Plan) {
    Write-Output "Plan: deploy a tracked deployment artifact, securely retrieve one bootstrap handoff, remove its remote plaintext, then run health and login smoke tests."
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

Receive-BootstrapCredentials -AzureCli $AzureCli -Metadata $metadata -CredentialsPath $CredentialsPath
& (Join-Path $PSScriptRoot "smoke.ps1") -AzureCli $AzureCli -MetadataPath $MetadataPath -CredentialsPath $CredentialsPath
if ($LASTEXITCODE -ne 0) {
    throw "Post-deploy smoke verification failed."
}
Write-Output "Deployment and post-deploy verification completed."
