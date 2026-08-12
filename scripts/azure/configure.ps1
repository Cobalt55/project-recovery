[CmdletBinding()]
param(
    [switch]$Plan,
    [string]$AzureCli,
    [string]$MetadataPath = (Join-Path $PSScriptRoot "..\..\local-secrets\azure-deployment.json"),
    [string]$OpenAiApiKeyPath = (Join-Path $PSScriptRoot "..\..\openai_api_service_key.txt"),
    [string]$VectorStoreIdPath = (Join-Path $PSScriptRoot "..\..\openai_vector_store_id.txt")
)

. (Join-Path $PSScriptRoot "common.ps1")

if ($Plan) {
    Write-Output "Plan: configure Key Vault references, managed identity, HTTPS, WebSockets, Always On, and a health path."
    exit 0
}

$AzureCli = Resolve-ApprovedAzureCli $AzureCli
Assert-ApprovedAzureIdentity $AzureCli
$metadata = Get-DeploymentMetadata $MetadataPath

foreach ($path in @($OpenAiApiKeyPath, $VectorStoreIdPath)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "A required local OpenAI input file is missing."
    }
}

$openAiApiKey = (Get-Content -LiteralPath $OpenAiApiKeyPath -Raw).Trim()
$vectorStoreId = (Get-Content -LiteralPath $VectorStoreIdPath -Raw).Trim()
if ([string]::IsNullOrWhiteSpace($openAiApiKey) -or [string]::IsNullOrWhiteSpace($vectorStoreId)) {
    throw "A required local OpenAI input file is empty."
}

Set-KeyVaultSecret -AzureCli $AzureCli -KeyVaultName $metadata.keyVaultName -Name "project-recovery-openai-api-key" -Value $openAiApiKey
Set-KeyVaultSecret -AzureCli $AzureCli -KeyVaultName $metadata.keyVaultName -Name "project-recovery-openai-vector-store-id" -Value $vectorStoreId
Set-KeyVaultSecret -AzureCli $AzureCli -KeyVaultName $metadata.keyVaultName -Name "project-recovery-app-session-secret" -Value (New-RandomSecret)
Set-KeyVaultSecret -AzureCli $AzureCli -KeyVaultName $metadata.keyVaultName -Name "project-recovery-chainlit-auth-secret" -Value (New-RandomSecret)

$identityJson = Invoke-ApprovedAzureCli -AzureCli $AzureCli -Arguments @(
    "webapp", "identity", "assign", "--resource-group", $metadata.resourceGroup,
    "--name", $metadata.webAppName, "--output", "json"
)
$principalId = ($identityJson | Out-String | ConvertFrom-Json).principalId
$keyVaultId = (Invoke-ApprovedAzureCli -AzureCli $AzureCli -Arguments @(
    "keyvault", "show", "--name", $metadata.keyVaultName, "--query", "id", "--output", "tsv"
) | Out-String).Trim()
Invoke-ApprovedAzureCli -AzureCli $AzureCli -Arguments @(
    "role", "assignment", "create", "--assignee-object-id", $principalId,
    "--assignee-principal-type", "ServicePrincipal", "--role", "Key Vault Secrets User",
    "--scope", $keyVaultId, "--output", "none"
) | Out-Null

$hostname = Get-WebAppHostName -AzureCli $AzureCli -ResourceGroup $metadata.resourceGroup -WebAppName $metadata.webAppName
Invoke-ApprovedAzureCli -AzureCli $AzureCli -Arguments @(
    "webapp", "config", "set", "--resource-group", $metadata.resourceGroup, "--name", $metadata.webAppName,
    "--always-on", "true", "--web-sockets-enabled", "true", "--min-tls-version", "1.2",
    "--health-check-path", "/health/ready", "--startup-file", "bash startup.sh", "--output", "none"
) | Out-Null
Invoke-ApprovedAzureCli -AzureCli $AzureCli -Arguments @(
    "webapp", "update", "--resource-group", $metadata.resourceGroup, "--name", $metadata.webAppName,
    "--https-only", "true", "--output", "none"
) | Out-Null
Invoke-ApprovedAzureCli -AzureCli $AzureCli -Arguments @(
    "webapp", "vnet-integration", "add", "--resource-group", $metadata.resourceGroup,
    "--name", $metadata.webAppName, "--vnet", $metadata.vnetName,
    "--subnet", $metadata.webAppSubnetName, "--output", "none"
) | Out-Null

$appSettings = @(
    "OPENAI_API_KEY=@Microsoft.KeyVault(SecretUri=$(Get-KeyVaultSecretId $AzureCli $metadata.keyVaultName 'project-recovery-openai-api-key'))",
    "OPENAI_VECTOR_STORE_ID=@Microsoft.KeyVault(SecretUri=$(Get-KeyVaultSecretId $AzureCli $metadata.keyVaultName 'project-recovery-openai-vector-store-id'))",
    "DATABASE_URL=@Microsoft.KeyVault(SecretUri=$(Get-KeyVaultSecretId $AzureCli $metadata.keyVaultName 'project-recovery-database-url'))",
    "APP_SESSION_SECRET=@Microsoft.KeyVault(SecretUri=$(Get-KeyVaultSecretId $AzureCli $metadata.keyVaultName 'project-recovery-app-session-secret'))",
    "CHAINLIT_AUTH_SECRET=@Microsoft.KeyVault(SecretUri=$(Get-KeyVaultSecretId $AzureCli $metadata.keyVaultName 'project-recovery-chainlit-auth-secret'))",
    "ENVIRONMENT=production",
    "TRUSTED_HOSTS=[`"$hostname`"]",
    "ATTACHMENT_STORAGE_PATH=/home/site/uploads",
    "SCM_DO_BUILD_DURING_DEPLOYMENT=true"
)
$appSettingsArguments = @(
    "webapp", "config", "appsettings", "set", "--resource-group", $metadata.resourceGroup,
    "--name", $metadata.webAppName, "--settings"
) + $appSettings
Invoke-ApprovedAzureCli -AzureCli $AzureCli -Arguments $appSettingsArguments | Out-Null

Write-Output "Configuration completed with Key Vault references and managed identity."
