Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ExpectedAzureUser = "amusheno@outlook.com"
$DefaultResourceGroup = "project-recovery-westus3-rg"
$DefaultLocation = "westus3"
$DefaultKeyVaultNamePrefix = "prwest3kv"

function Get-RepositoryRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot "..\..") -ErrorAction Stop).Path
}

function Resolve-ApprovedAzureCli {
    param([string]$AzureCli)

    if ([string]::IsNullOrWhiteSpace($AzureCli)) {
        $commonGitDirectory = (& git -C (Get-RepositoryRoot) rev-parse --path-format=absolute --git-common-dir).Trim()
        if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($commonGitDirectory)) {
            throw "Unable to locate the repository root for the approved Azure wrapper."
        }
        $repositoryRoot = Split-Path -Parent $commonGitDirectory
        $AzureCli = Join-Path $repositoryRoot "az-amusheno.ps1"
    }
    $resolved = Resolve-Path -LiteralPath $AzureCli -ErrorAction Stop
    if ($resolved.Path -notlike "*az-amusheno.ps1") {
        throw "Azure commands must use the approved az-amusheno.ps1 wrapper."
    }
    return $resolved.Path
}

function Invoke-ApprovedAzureCli {
    param(
        [Parameter(Mandatory)][string]$AzureCli,
        [Parameter(Mandatory)][string[]]$Arguments
    )

    $result = & $AzureCli @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "The approved Azure wrapper failed while running a requested operation."
    }
    return $result
}

function Assert-ApprovedAzureIdentity {
    param([Parameter(Mandatory)][string]$AzureCli)

    $activeUser = (Invoke-ApprovedAzureCli -AzureCli $AzureCli -Arguments @(
        "account", "show", "--query", "user.name", "--output", "tsv"
    ) | Out-String).Trim()
    if ($activeUser -ne $ExpectedAzureUser) {
        throw "Expected Azure identity $ExpectedAzureUser; refusing to continue."
    }
}

function Get-DeploymentMetadata {
    param([string]$MetadataPath)

    if (-not (Test-Path -LiteralPath $MetadataPath -PathType Leaf)) {
        throw "Deployment metadata is missing. Run provision.ps1 first."
    }
    return Get-Content -LiteralPath $MetadataPath -Raw | ConvertFrom-Json
}

function Save-DeploymentMetadata {
    param(
        [Parameter(Mandatory)][object]$Metadata,
        [Parameter(Mandatory)][string]$MetadataPath
    )

    $directory = Split-Path -Parent $MetadataPath
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
    $Metadata | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $MetadataPath -Encoding utf8
}

function New-SafeResourceName {
    param([Parameter(Mandatory)][string]$Prefix)

    $suffix = -join ((1..10) | ForEach-Object { "abcdefghijklmnopqrstuvwxyz0123456789"[(Get-Random -Maximum 36)] })
    return "$Prefix-$suffix"
}

function ConvertTo-Plaintext {
    param([Parameter(Mandatory)][Security.SecureString]$SecureValue)

    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureValue)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
}

function New-RandomSecret {
    param([int]$Bytes = 32)

    $buffer = New-Object byte[] $Bytes
    [Security.Cryptography.RandomNumberGenerator]::Fill($buffer)
    return [Convert]::ToBase64String($buffer)
}

function Set-KeyVaultSecret {
    param(
        [Parameter(Mandatory)][string]$AzureCli,
        [Parameter(Mandatory)][string]$KeyVaultName,
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$Value
    )

    Invoke-ApprovedAzureCli -AzureCli $AzureCli -Arguments @(
        "keyvault", "secret", "set", "--vault-name", $KeyVaultName, "--name", $Name,
        "--value", $Value, "--output", "none"
    ) | Out-Null
}

function Get-KeyVaultSecretId {
    param(
        [Parameter(Mandatory)][string]$AzureCli,
        [Parameter(Mandatory)][string]$KeyVaultName,
        [Parameter(Mandatory)][string]$Name
    )

    return (Invoke-ApprovedAzureCli -AzureCli $AzureCli -Arguments @(
        "keyvault", "secret", "show", "--vault-name", $KeyVaultName, "--name", $Name,
        "--query", "id", "--output", "tsv"
    ) | Out-String).Trim()
}

function Get-WebAppHostName {
    param(
        [Parameter(Mandatory)][string]$AzureCli,
        [Parameter(Mandatory)][string]$ResourceGroup,
        [Parameter(Mandatory)][string]$WebAppName
    )

    return (Invoke-ApprovedAzureCli -AzureCli $AzureCli -Arguments @(
        "webapp", "show", "--resource-group", $ResourceGroup, "--name", $WebAppName,
        "--query", "defaultHostName", "--output", "tsv"
    ) | Out-String).Trim()
}
