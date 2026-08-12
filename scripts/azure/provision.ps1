[CmdletBinding()]
param(
    [switch]$Plan,
    [string]$AzureCli,
    [string]$ResourceGroup = "project-recovery-westus3-rg",
    [string]$Location = "westus3",
    [string]$AppServicePlanName = "project-recovery-westus3-b3-plan",
    [string]$WebAppName = "project-recovery-chat-wus3-amush",
    [string]$KeyVaultName = "project-recovery-kv-wus3",
    [string]$PostgresServerName = "project-recovery-pg-wus3-amush",
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
    if ($existing.provisioningState -eq "complete") {
        Write-Output "Provisioning already completed for Web App $($existing.webAppName)."
        exit 0
    }
    Write-Output "Resuming incomplete provisioning for Web App $($existing.webAppName)."
}

$subscriptionId = (Invoke-ApprovedAzureCli -AzureCli $AzureCli -Arguments @(
    "account", "show", "--query", "id", "--output", "tsv"
) | Out-String).Trim()
$signedInUserObjectId = (Invoke-ApprovedAzureCli -AzureCli $AzureCli -Arguments @(
    "ad", "signed-in-user", "show", "--query", "id", "--output", "tsv"
) | Out-String).Trim()
function Assert-RegionalAppServiceQuota {
    $regionalQuotaJson = Invoke-ApprovedAzureCli -AzureCli $AzureCli -Arguments @(
        "rest", "--method", "get",
        "--url", "https://management.azure.com/subscriptions/$subscriptionId/providers/Microsoft.Web/locations/$Location/usages?api-version=2025-05-01",
        "--query", "value[?name.value=='*'] | [0].{current:currentValue,limit:limit}",
        "--output", "json"
    )
    $regionalQuota = $regionalQuotaJson | Out-String | ConvertFrom-Json
    if ($null -eq $regionalQuota -or [int]$regionalQuota.limit -lt 1) {
        throw "App Service Total Regional VMs quota is zero in $Location. Request a quota increase before provisioning."
    }
}

$normalizedLocation = ($Location -replace " ", "").ToLowerInvariant()
$databaseName = "projectrecovery"
$vnetName = "$WebAppName-vnet"
$postgresSubnetName = "postgres"
$webAppSubnetName = "webapp"
$privateDnsZoneName = "$WebAppName.private.postgres.database.azure.com"

$resourceGroupExists = (Invoke-ApprovedAzureCli -AzureCli $AzureCli -Arguments @(
    "group", "exists", "--name", $ResourceGroup, "--output", "tsv"
) | Out-String).Trim()
if ($resourceGroupExists -ne "true") {
    Assert-RegionalAppServiceQuota
    Invoke-ApprovedAzureCli -AzureCli $AzureCli -Arguments @(
        "group", "create", "--name", $ResourceGroup, "--location", $Location, "--output", "none"
    ) | Out-Null
}
else {
    $resourceGroupLocation = (Invoke-ApprovedAzureCli -AzureCli $AzureCli -Arguments @(
        "group", "show", "--name", $ResourceGroup, "--query", "location", "--output", "tsv"
    ) | Out-String).Trim()
    if (($resourceGroupLocation -replace " ", "").ToLowerInvariant() -ne $normalizedLocation) {
        throw "The existing deployment resource group is not in the requested location."
    }
}
$existingPlanJson = Invoke-ApprovedAzureCli -AzureCli $AzureCli -Arguments @(
    "appservice", "plan", "list", "--resource-group", $ResourceGroup,
    "--query", "[?name=='$AppServicePlanName'] | [0].{id:id,location:location,kind:kind,sku:sku.name}",
    "--output", "json"
)
$existingPlan = $existingPlanJson | Out-String | ConvertFrom-Json
if ($null -eq $existingPlan) {
    Assert-RegionalAppServiceQuota
    Invoke-ApprovedAzureCli -AzureCli $AzureCli -Arguments @(
        "appservice", "plan", "create", "--resource-group", $ResourceGroup, "--name", $AppServicePlanName,
        "--location", $Location, "--sku", "B3", "--is-linux", "--output", "none"
    ) | Out-Null
    $existingPlanJson = Invoke-ApprovedAzureCli -AzureCli $AzureCli -Arguments @(
        "appservice", "plan", "list", "--resource-group", $ResourceGroup,
        "--query", "[?name=='$AppServicePlanName'] | [0].{id:id,location:location,kind:kind,sku:sku.name}",
        "--output", "json"
    )
    $existingPlan = $existingPlanJson | Out-String | ConvertFrom-Json
}
if ($null -eq $existingPlan -or
    (($existingPlan.location -replace " ", "").ToLowerInvariant() -ne $normalizedLocation) -or
    $existingPlan.kind -notmatch "(?i)linux" -or
    $existingPlan.sku -ne "B3") {
    throw "The App Service plan must be a Linux B3 plan in $Location."
}
$existingWebAppJson = Invoke-ApprovedAzureCli -AzureCli $AzureCli -Arguments @(
    "webapp", "list", "--resource-group", $ResourceGroup,
    "--query", "[?name=='$WebAppName'] | [0].{location:location,appServicePlanId:appServicePlanId,kind:kind}",
    "--output", "json"
)
$existingWebApp = $existingWebAppJson | Out-String | ConvertFrom-Json
if ($null -eq $existingWebApp) {
    Invoke-ApprovedAzureCli -AzureCli $AzureCli -Arguments @(
        "webapp", "create", "--resource-group", $ResourceGroup, "--plan", $AppServicePlanName, "--name", $WebAppName,
        "--runtime", "PYTHON:3.12", "--output", "none"
    ) | Out-Null
}
elseif ((($existingWebApp.location -replace " ", "").ToLowerInvariant() -ne $normalizedLocation) -or
        $existingWebApp.appServicePlanId -ine $existingPlan.id -or
        $existingWebApp.kind -notmatch "(?i)linux") {
    throw "The existing Web App must be Linux, in $Location, and attached to $AppServicePlanName."
}
if ($null -ne $existingWebApp) {
    $existingLinuxFxVersion = (Invoke-ApprovedAzureCli -AzureCli $AzureCli -Arguments @(
        "webapp", "config", "show", "--resource-group", $ResourceGroup, "--name", $WebAppName,
        "--query", "linuxFxVersion", "--output", "tsv"
    ) | Out-String).Trim()
    if ($existingLinuxFxVersion -ine "PYTHON|3.12") {
        throw "The existing Web App must use PYTHON|3.12."
    }
}

Save-DeploymentMetadata -Metadata ([ordered]@{
    provisioningState = "in-progress"
    subscriptionId = $subscriptionId
    resourceGroup = $ResourceGroup
    location = $Location
    keyVaultName = $KeyVaultName
    webAppName = $WebAppName
    appServicePlanName = $AppServicePlanName
    postgresServerName = $PostgresServerName
    databaseName = $databaseName
    vnetName = $vnetName
    postgresSubnetName = $postgresSubnetName
    webAppSubnetName = $webAppSubnetName
    privateDnsZoneName = $privateDnsZoneName
}) -MetadataPath $MetadataPath

$existingKeyVaultJson = Invoke-ApprovedAzureCli -AzureCli $AzureCli -Arguments @(
    "keyvault", "list", "--resource-group", $ResourceGroup,
    "--query", "[?name=='$KeyVaultName'] | [0].{id:id,location:location,enableRbacAuthorization:properties.enableRbacAuthorization}",
    "--output", "json"
)
$existingKeyVault = $existingKeyVaultJson | Out-String | ConvertFrom-Json
if ($null -eq $existingKeyVault) {
    Invoke-ApprovedAzureCli -AzureCli $AzureCli -Arguments @(
        "keyvault", "create", "--resource-group", $ResourceGroup, "--name", $KeyVaultName,
        "--location", $Location, "--enable-rbac-authorization", "true", "--output", "none"
    ) | Out-Null
    $keyVaultId = (Invoke-ApprovedAzureCli -AzureCli $AzureCli -Arguments @(
        "keyvault", "show", "--name", $KeyVaultName, "--query", "id", "--output", "tsv"
    ) | Out-String).Trim()
}
elseif ((($existingKeyVault.location -replace " ", "").ToLowerInvariant() -ne $normalizedLocation) -or
        $existingKeyVault.enableRbacAuthorization -ne $true) {
    throw "The existing Key Vault must use RBAC authorization in $Location."
}
else {
    $keyVaultId = $existingKeyVault.id
}
$keyVaultOfficerAssignmentCount = (Invoke-ApprovedAzureCli -AzureCli $AzureCli -Arguments @(
    "role", "assignment", "list", "--assignee-object-id", $signedInUserObjectId, "--scope", $keyVaultId,
    "--query", "[?roleDefinitionName=='Key Vault Secrets Officer'] | length(@)", "--output", "tsv"
) | Out-String).Trim()
if ($keyVaultOfficerAssignmentCount -eq "0") {
    Invoke-ApprovedAzureCli -AzureCli $AzureCli -Arguments @(
        "role", "assignment", "create", "--assignee-object-id", $signedInUserObjectId,
        "--assignee-principal-type", "User", "--role", "Key Vault Secrets Officer",
        "--scope", $keyVaultId, "--output", "none"
    ) | Out-Null
}
$existingVnetJson = Invoke-ApprovedAzureCli -AzureCli $AzureCli -Arguments @(
    "network", "vnet", "list", "--resource-group", $ResourceGroup,
    "--query", "[?name=='$vnetName'] | [0].{location:location}", "--output", "json"
)
$existingVnet = $existingVnetJson | Out-String | ConvertFrom-Json
if ($null -eq $existingVnet) {
    Invoke-ApprovedAzureCli -AzureCli $AzureCli -Arguments @(
        "network", "vnet", "create", "--resource-group", $ResourceGroup, "--name", $vnetName,
        "--location", $Location, "--address-prefixes", "10.20.0.0/16", "--output", "none"
    ) | Out-Null
}
elseif (($existingVnet.location -replace " ", "").ToLowerInvariant() -ne $normalizedLocation) {
    throw "The existing virtual network is not in the requested location."
}
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
    $existingPostgresJson = Invoke-ApprovedAzureCli -AzureCli $AzureCli -Arguments @(
        "postgres", "flexible-server", "list", "--resource-group", $ResourceGroup,
        "--query", "[?name=='$PostgresServerName'] | [0].{location:location}", "--output", "json"
    )
    $existingPostgres = $existingPostgresJson | Out-String | ConvertFrom-Json
    if ($null -eq $existingPostgres) {
        Invoke-ApprovedAzureCli -AzureCli $AzureCli -Arguments @(
            "postgres", "flexible-server", "create", "--resource-group", $ResourceGroup,
            "--name", $PostgresServerName, "--location", $Location, "--admin-user", "projectrecoveryadmin",
            "--admin-password", $postgresPassword, "--sku-name", "Standard_B1ms", "--tier", "Burstable",
            "--storage-size", "32", "--backup-retention", "7", "--high-availability", "Disabled",
            "--version", "16", "--vnet", $vnetName, "--subnet", $postgresSubnetName,
            "--private-dns-zone", $privateDnsZoneName, "--output", "none"
        ) | Out-Null
    }
    elseif (($existingPostgres.location -replace " ", "").ToLowerInvariant() -ne $normalizedLocation) {
        throw "The existing PostgreSQL server is not in the requested location."
    }
    else {
        Invoke-ApprovedAzureCli -AzureCli $AzureCli -Arguments @(
            "postgres", "flexible-server", "update", "--resource-group", $ResourceGroup,
            "--name", $PostgresServerName, "--admin-password", $postgresPassword, "--output", "none"
        ) | Out-Null
    }
    $databaseExists = (Invoke-ApprovedAzureCli -AzureCli $AzureCli -Arguments @(
        "postgres", "flexible-server", "db", "list", "--resource-group", $ResourceGroup,
        "--server-name", $PostgresServerName,
        "--query", "[?name=='$databaseName'] | length(@)", "--output", "tsv"
    ) | Out-String).Trim()
    if ($databaseExists -eq "0") {
        Invoke-ApprovedAzureCli -AzureCli $AzureCli -Arguments @(
            "postgres", "flexible-server", "db", "create", "--resource-group", $ResourceGroup,
            "--server-name", $PostgresServerName, "--database-name", $databaseName, "--output", "none"
        ) | Out-Null
    }
    $databaseUrl = "postgresql+asyncpg://projectrecoveryadmin:$([uri]::EscapeDataString($postgresPassword))@${PostgresServerName}.postgres.database.azure.com:5432/${databaseName}?ssl=require"
    Set-KeyVaultSecret -AzureCli $AzureCli -KeyVaultName $KeyVaultName -Name "project-recovery-database-url" -Value $databaseUrl
}
finally {
    $postgresPassword = $null
}

Save-DeploymentMetadata -Metadata ([ordered]@{
    provisioningState = "complete"
    subscriptionId = $subscriptionId
    resourceGroup = $ResourceGroup
    location = $Location
    keyVaultName = $KeyVaultName
    webAppName = $WebAppName
    appServicePlanName = $AppServicePlanName
    postgresServerName = $PostgresServerName
    databaseName = $databaseName
    vnetName = $vnetName
    postgresSubnetName = $postgresSubnetName
    webAppSubnetName = $webAppSubnetName
    privateDnsZoneName = $privateDnsZoneName
}) -MetadataPath $MetadataPath
Write-Output "Provisioning completed. Non-secret deployment metadata was saved locally."
