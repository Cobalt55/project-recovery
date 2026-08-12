[CmdletBinding()]
param(
    [switch]$Plan,
    [string]$AzureCli,
    [string]$ResourceGroup = "recovery-az-web-app_group",
    [string]$Location = "eastus2",
    [string]$KeyVaultName = "recovery-az-key-vault",
    [string]$MetadataPath = (Join-Path $PSScriptRoot "..\..\local-secrets\azure-deployment.json"),
    [Security.SecureString]$PostgresAdminPassword
)

. (Join-Path $PSScriptRoot "common.ps1")

if ($Plan) {
    Write-Output "Plan: Basic B3 Linux App Service, PostgreSQL Flexible Server B1ms, and metadata only."
    exit 0
}

$AzureCli = Resolve-ApprovedAzureCli $AzureCli
Assert-ApprovedAzureIdentity $AzureCli

if (Test-Path -LiteralPath $MetadataPath -PathType Leaf) {
    $existing = Get-DeploymentMetadata $MetadataPath
    Write-Output "Provisioning already recorded for Web App $($existing.webAppName)."
    exit 0
}

$subscriptionId = (Invoke-ApprovedAzureCli -AzureCli $AzureCli -Arguments @(
    "account", "show", "--query", "id", "--output", "tsv"
) | Out-String).Trim()
$webAppName = New-SafeResourceName "project-recovery-chat"
$planName = "$webAppName-plan"
$postgresServerName = New-SafeResourceName "project-recovery-chat-db"
$databaseName = "projectrecovery"
$vnetName = "$webAppName-vnet"
$postgresSubnetName = "postgres"
$webAppSubnetName = "webapp"
$privateDnsZoneName = "$webAppName.private.postgres.database.azure.com"

Invoke-ApprovedAzureCli -AzureCli $AzureCli -Arguments @(
    "group", "create", "--name", $ResourceGroup, "--location", $Location, "--output", "none"
) | Out-Null
Invoke-ApprovedAzureCli -AzureCli $AzureCli -Arguments @(
    "appservice", "plan", "create", "--resource-group", $ResourceGroup, "--name", $planName,
    "--sku", "B3", "--is-linux", "--output", "none"
) | Out-Null
Invoke-ApprovedAzureCli -AzureCli $AzureCli -Arguments @(
    "webapp", "create", "--resource-group", $ResourceGroup, "--plan", $planName, "--name", $webAppName,
    "--runtime", "PYTHON:3.12", "--output", "none"
) | Out-Null
Invoke-ApprovedAzureCli -AzureCli $AzureCli -Arguments @(
    "network", "vnet", "create", "--resource-group", $ResourceGroup, "--name", $vnetName,
    "--location", $Location, "--address-prefixes", "10.20.0.0/16", "--output", "none"
) | Out-Null
Invoke-ApprovedAzureCli -AzureCli $AzureCli -Arguments @(
    "network", "vnet", "subnet", "create", "--resource-group", $ResourceGroup,
    "--vnet-name", $vnetName, "--name", $postgresSubnetName,
    "--address-prefixes", "10.20.1.0/24",
    "--delegations", "Microsoft.DBforPostgreSQL/flexibleServers", "--output", "none"
) | Out-Null
Invoke-ApprovedAzureCli -AzureCli $AzureCli -Arguments @(
    "network", "vnet", "subnet", "create", "--resource-group", $ResourceGroup,
    "--vnet-name", $vnetName, "--name", $webAppSubnetName,
    "--address-prefixes", "10.20.2.0/24",
    "--delegations", "Microsoft.Web/serverFarms", "--output", "none"
) | Out-Null

if ($null -eq $PostgresAdminPassword) {
    $PostgresAdminPassword = ConvertTo-SecureString (New-RandomSecret) -AsPlainText -Force
}
$postgresPassword = ConvertTo-Plaintext $PostgresAdminPassword
try {
    Invoke-ApprovedAzureCli -AzureCli $AzureCli -Arguments @(
        "postgres", "flexible-server", "create", "--resource-group", $ResourceGroup,
        "--name", $postgresServerName, "--location", $Location, "--admin-user", "projectrecoveryadmin",
        "--admin-password", $postgresPassword, "--sku-name", "Standard_B1ms", "--tier", "Burstable",
        "--storage-size", "32", "--backup-retention", "7", "--high-availability", "Disabled",
        "--version", "16", "--vnet", $vnetName, "--subnet", $postgresSubnetName,
        "--private-dns-zone", $privateDnsZoneName, "--output", "none"
    ) | Out-Null
    Invoke-ApprovedAzureCli -AzureCli $AzureCli -Arguments @(
        "postgres", "flexible-server", "db", "create", "--resource-group", $ResourceGroup,
        "--server-name", $postgresServerName, "--database-name", $databaseName, "--output", "none"
    ) | Out-Null
    $databaseUrl = "postgresql+asyncpg://projectrecoveryadmin:$([uri]::EscapeDataString($postgresPassword))@$postgresServerName.postgres.database.azure.com:5432/$databaseName?ssl=require"
    Set-KeyVaultSecret -AzureCli $AzureCli -KeyVaultName $KeyVaultName -Name "project-recovery-database-url" -Value $databaseUrl
}
finally {
    $postgresPassword = $null
}

Save-DeploymentMetadata -Metadata ([ordered]@{
    subscriptionId = $subscriptionId
    resourceGroup = $ResourceGroup
    location = $Location
    keyVaultName = $KeyVaultName
    webAppName = $webAppName
    appServicePlanName = $planName
    postgresServerName = $postgresServerName
    databaseName = $databaseName
    vnetName = $vnetName
    postgresSubnetName = $postgresSubnetName
    webAppSubnetName = $webAppSubnetName
    privateDnsZoneName = $privateDnsZoneName
}) -MetadataPath $MetadataPath
Write-Output "Provisioning completed. Non-secret deployment metadata was saved locally."
