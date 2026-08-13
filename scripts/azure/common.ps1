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

function Initialize-PrivateCredentialDirectory {
    param([Parameter(Mandatory)][string]$CredentialsPath)

    $directory = Split-Path -Parent $CredentialsPath
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
    if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
        return
    }

    $windowsPowerShell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    if (-not (Test-Path -LiteralPath $windowsPowerShell -PathType Leaf)) {
        throw "Windows PowerShell is required to secure the credential directory."
    }
    $previousPath = [Environment]::GetEnvironmentVariable(
        "PROJECT_RECOVERY_CREDENTIALS_DIRECTORY",
        "Process"
    )
    [Environment]::SetEnvironmentVariable(
        "PROJECT_RECOVERY_CREDENTIALS_DIRECTORY",
        (Resolve-Path -LiteralPath $directory).Path,
        "Process"
    )
    $aclScript = @'
$ErrorActionPreference = 'Stop'
$path = [Environment]::GetEnvironmentVariable('PROJECT_RECOVERY_CREDENTIALS_DIRECTORY')
if ([string]::IsNullOrWhiteSpace($path)) { throw 'credential directory is required' }
$resolved = (Resolve-Path -LiteralPath $path).Path
$sid = [Security.Principal.WindowsIdentity]::GetCurrent().User
$directoryInfo = [System.IO.DirectoryInfo]::new($resolved)
$acl = $directoryInfo.GetAccessControl()
$acl.SetAccessRuleProtection($true, $false)
foreach ($rule in @($acl.Access)) { [void]$acl.RemoveAccessRuleAll($rule) }
$inheritance = 'ContainerInherit,ObjectInherit'
$rule = New-Object Security.AccessControl.FileSystemAccessRule(
    $sid, 'FullControl', $inheritance, 'None', 'Allow'
)
[void]$acl.AddAccessRule($rule)
$acl.SetOwner($sid)
$directoryInfo.SetAccessControl($acl)
$verified = $directoryInfo.GetAccessControl()
$ownerSid = $verified.GetOwner([Security.Principal.SecurityIdentifier])
$rules = @($verified.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier]))
$fullControl = [Security.AccessControl.FileSystemRights]::FullControl
$current = @($rules | Where-Object {
    $_.IdentityReference -eq $sid -and $_.AccessControlType -eq 'Allow' -and
    (($_.FileSystemRights -band $fullControl) -eq $fullControl)
})
$other = @($rules | Where-Object { $_.IdentityReference -ne $sid })
$valid = $verified.AreAccessRulesProtected -and $ownerSid -eq $sid
$valid = $valid -and $current.Count -eq 1 -and $other.Count -eq 0
[pscustomobject]@{
    valid = $valid
    canonical_path = $resolved
    current_sid = $sid.Value
    owner_sid = $ownerSid.Value
    dacl_protected = $verified.AreAccessRulesProtected
    current_full_control_rules = $current.Count
    other_access_rules = $other.Count
} | ConvertTo-Json -Compress
'@
    try {
        $verificationJson = & $windowsPowerShell -NoProfile -NonInteractive -Command $aclScript
        if ($LASTEXITCODE -ne 0) {
            throw "Unable to secure the credential directory."
        }
        $verification = $verificationJson | Out-String | ConvertFrom-Json
        $resolvedDirectory = (Resolve-Path -LiteralPath $directory).Path
        if (
            $verification.valid -ne $true -or
            $verification.canonical_path -ne $resolvedDirectory -or
            [string]::IsNullOrWhiteSpace($verification.current_sid) -or
            $verification.owner_sid -ne $verification.current_sid -or
            $verification.dacl_protected -ne $true -or
            $verification.current_full_control_rules -ne 1 -or
            $verification.other_access_rules -ne 0
        ) {
            throw "Unable to validate the credential directory ACL."
        }
    }
    finally {
        [Environment]::SetEnvironmentVariable(
            "PROJECT_RECOVERY_CREDENTIALS_DIRECTORY",
            $previousPath,
            "Process"
        )
    }
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
