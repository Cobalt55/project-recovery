[CmdletBinding()]
param(
    [switch]$Plan,
    [string]$AzureCli,
    [string]$MetadataPath = (Join-Path $PSScriptRoot "..\..\local-secrets\azure-deployment.json"),
    [string]$CredentialsPath = (Join-Path $PSScriptRoot "..\..\local-secrets\bootstrap-credentials.txt")
)

. (Join-Path $PSScriptRoot "common.ps1")

function Invoke-NoRedirectWebRequest {
    param(
        [Parameter(Mandatory)][string]$Uri,
        [ValidateSet("Get", "Post")][string]$Method = "Get",
        [hashtable]$Body
    )

    $handler = [System.Net.Http.HttpClientHandler]::new()
    $handler.AllowAutoRedirect = $false
    $client = [System.Net.Http.HttpClient]::new($handler)
    $content = $null
    try {
        if ($Method -eq "Post") {
            $pairs = [System.Collections.Generic.List[System.Collections.Generic.KeyValuePair[string, string]]]::new()
            foreach ($key in $Body.Keys) {
                $pairs.Add([System.Collections.Generic.KeyValuePair[string, string]]::new($key, [string]$Body[$key]))
            }
            $content = [System.Net.Http.FormUrlEncodedContent]::new($pairs)
            $response = $client.PostAsync($Uri, $content).GetAwaiter().GetResult()
        }
        else {
            $response = $client.GetAsync($Uri).GetAwaiter().GetResult()
        }
        $location = if ($null -ne $response.Headers.Location) {
            $response.Headers.Location.OriginalString
        }
        else {
            $null
        }
        return [pscustomobject]@{
            StatusCode = [int]$response.StatusCode
            Headers = [pscustomobject]@{ Location = $location }
        }
    }
    finally {
        if ($null -ne $content) {
            $content.Dispose()
        }
        $client.Dispose()
        $handler.Dispose()
    }
}

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
    $response = Invoke-NoRedirectWebRequest -Uri "$baseUri$path"
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
$login = Invoke-NoRedirectWebRequest -Uri "$baseUri/login" -Method Post -Body @{ email = $email; password = $password }
$acceptedLoginDestinations = @("/password/change", "/chat")
if ($login.StatusCode -ne 303 -or $login.Headers.Location -notin $acceptedLoginDestinations) {
    throw "Production authenticated login smoke test failed."
}
Write-Output "Production health and authenticated login smoke test passed."
