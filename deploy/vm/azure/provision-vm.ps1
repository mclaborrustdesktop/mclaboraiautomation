# The single-VM Azure resources as Azure CLI commands. DRY RUN BY DEFAULT: prints every command, runs none.
#   powershell -ExecutionPolicy Bypass -File deploy\vm\azure\provision-vm.ps1                       (plan)
#   powershell -ExecutionPolicy Bypass -File deploy\vm\azure\provision-vm.ps1 -Execute              (creates resources: needs the owner's go-ahead)
# What it creates (docs/cloud/07-single-vm-plan.md): resource group, VNet + subnet, NSG with NO inbound rule,
# a Standard public IP used for outbound internet only, the VM (Standard_B4ms, Windows Server 2022 with SQL Server
# 2019 Express from the marketplace image, Standard SSD disks), daily Azure Backup of the VM (30 days), a storage
# account + container for the encrypted SQL backups with a lifecycle rule, Log Analytics + metric alerts, and the
# 200 USD budget with alerts at 50/75/90/100 %.
param(
    [switch]$Execute,
    [ValidateSet('production', 'staging')][string]$Environment = 'production',
    [string]$Subscription = '<subscription id>',
    [string]$Location = 'eastus',
    [string]$ResourceGroup = '',                 # default: rg-mclabor (production) / rg-mclabor-staging
    [string]$VmName = '',                        # default: vm-mclabor / vm-mclabor-stg
    [string]$VmSize = 'Standard_B2ms',           # enough for 20 users (docs/cloud/11); -VmSize Standard_B4ms for the larger size; resize later takes minutes
    [string]$Image = 'MicrosoftSQLServer:sql2019-ws2022:express-gen2:latest',   # confirm the exact SKU name with: az vm image list-skus -l eastus -p MicrosoftSQLServer -f sql2019-ws2022 -o table
    [string]$AdminUser = 'mcladmin',
    [string]$AdminPassword = '<the VM administrator password: pass -AdminPassword (Read-Host -AsSecureString ... converted) or type it when asked>',
    [string]$AlertEmail = '<owner@mclabor.com>',
    [string]$StorageAccount = '',                # default: stmclaborbackup<unique> / stmclaborstg<unique>
    [int]$BudgetUsd = 0,                         # default: 200 (production) / 50 (staging)
    [string]$AutoShutdownTime = '',              # staging default 19:00 (VM deallocated every evening; compute stops being billed)
    [switch]$SkipVmBackup                        # staging default: on (synthetic data needs no Azure Backup)
)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$lifecycle = Join-Path $here 'lifecycle.json'           # Join-Path: works in Windows PowerShell and in Azure Cloud Shell (Linux)
$dcrTemplate = Join-Path $here 'dcr-events.json'
$dcrGenerated = Join-Path $here 'dcr-events.generated.json'
$staging = $Environment -eq 'staging'
if ($Execute -and $AdminPassword -like '<*') {
    $secure = Read-Host -AsSecureString "Administrator password for the VM (20+ characters; typing is hidden; store it in the password safe)"
    $AdminPassword = (New-Object System.Net.NetworkCredential('', $secure)).Password
    if ($AdminPassword.Length -lt 20) { throw 'Password shorter than 20 characters. Nothing was created.' }
}
$AdminPasswordQuoted = "'" + ($AdminPassword -replace "'", "''") + "'"    # safe for any character in the password
if (-not $ResourceGroup) { $ResourceGroup = if ($staging) { 'rg-mclabor-staging' } else { 'rg-mclabor' } }
if (-not $VmName) { $VmName = if ($staging) { 'vm-mclabor-stg' } else { 'vm-mclabor' } }
if (-not $StorageAccount) { $StorageAccount = if ($staging) { 'stmclaborstg<unique>' } else { 'stmclaborbackup<unique>' } }
if (-not $BudgetUsd) { $BudgetUsd = if ($staging) { 50 } else { 200 } }
if (-not $AutoShutdownTime -and $staging) { $AutoShutdownTime = '1900' }
if ($staging -and -not $PSBoundParameters.ContainsKey('SkipVmBackup')) { $SkipVmBackup = $true }
$plan = @(
    "az account set --subscription $Subscription",
    "az group create --name $ResourceGroup --location $Location --tags project=mclabor environment=$Environment data=$(if ($staging) { 'synthetic-only' } else { 'real' })",
    # network: one subnet; the NSG has no inbound allow rule at all (the Azure default rules deny the internet)
    "az network nsg create --resource-group $ResourceGroup --name nsg-mclabor",
    "az network nsg rule create --resource-group $ResourceGroup --nsg-name nsg-mclabor --name deny-all-inbound --priority 100 --direction Inbound --access Deny --protocol '*' --source-address-prefixes '*' --destination-port-ranges '*'",
    "az network vnet create --resource-group $ResourceGroup --name vnet-mclabor --address-prefixes 10.20.0.0/16 --subnet-name snet-vm --subnet-prefixes 10.20.1.0/24 --network-security-group nsg-mclabor",
    # the public IP exists only so the VM can reach the internet (Cloudflare, Windows Update, backups); the NSG denies every inbound packet to it
    "az network public-ip create --resource-group $ResourceGroup --name pip-mclabor-outbound --sku Standard --allocation-method Static",
    "az network nic create --resource-group $ResourceGroup --name nic-mclabor --vnet-name vnet-mclabor --subnet snet-vm --public-ip-address pip-mclabor-outbound --private-ip-address 10.20.1.4",
    # the VM: Windows Server 2022 + SQL Server 2019 Express (free licence) from Microsoft's image; Standard SSD disks
    "az vm create --resource-group $ResourceGroup --name $VmName --image $Image --size $VmSize --nics nic-mclabor --admin-username $AdminUser --admin-password `$AdminPasswordQuoted --os-disk-size-gb 128 --storage-sku StandardSSD_LRS --license-type Windows_Server",
    "az vm disk attach --resource-group $ResourceGroup --vm-name $VmName --name disk-mclabor-data --new --size-gb 64 --sku StandardSSD_LRS",
    "az sql vm create --resource-group $ResourceGroup --name $VmName --license-type PAYG --sql-mgmt-type Full --connectivity-type PRIVATE --port 1433",
    "az vm boot-diagnostics enable --resource-group $ResourceGroup --name $VmName",
    "az vm update --resource-group $ResourceGroup --name $VmName --set osProfile.windowsConfiguration.patchSettings.patchMode=AutomaticByPlatform"
) + $(if ($AutoShutdownTime) { @(
    # staging: deallocated every evening so compute is billed only on test days (disks and the IP keep billing)
    "az vm auto-shutdown --resource-group $ResourceGroup --name $VmName --time $AutoShutdownTime --email $AlertEmail") } else { @() }
) + $(if (-not $SkipVmBackup) { @(
    # backups: the whole VM daily (30 days)
    "az backup vault create --resource-group $ResourceGroup --name rsv-mclabor --location $Location",
    "az backup vault backup-properties set --resource-group $ResourceGroup --name rsv-mclabor --backup-storage-redundancy LocallyRedundant",
    "az backup protection enable-for-vm --resource-group $ResourceGroup --vault-name rsv-mclabor --vm $VmName --policy-name DefaultPolicy") } else { @() }
) + @(
    # a storage account for the encrypted SQL backups (cool tier, 35 daily / 12 monthly by lifecycle rule)
    "az storage account create --resource-group $ResourceGroup --name $StorageAccount --sku Standard_LRS --kind StorageV2 --access-tier Cool --min-tls-version TLS1_2 --allow-blob-public-access false",
    "az storage container create --account-name $StorageAccount --name sqlbackups --auth-mode login",
    "az storage account management-policy create --account-name $StorageAccount --resource-group $ResourceGroup --policy `"@$lifecycle`"",
    # a write-only (add + create, no read/delete) SAS for the VM's upload task, 1 year: generated when the VM is set up (SETUP.md step 8)
    # monitoring: metric alerts on the VM (first 10 metric alert rules are free), an action group that e-mails the owner
    "az monitor log-analytics workspace create --resource-group $ResourceGroup --workspace-name log-mclabor --retention-time 30",
    "az monitor action-group create --resource-group $ResourceGroup --name ag-mclabor-owner --short-name mclabor --action email owner $AlertEmail",
    "az monitor metrics alert create --resource-group $ResourceGroup --name alert-vm-cpu --scopes (az vm show -g $ResourceGroup -n $VmName --query id -o tsv) --condition 'avg Percentage CPU > 90' --window-size 15m --evaluation-frequency 5m --action ag-mclabor-owner --description 'VM CPU over 90% for 15 minutes'",
    "az monitor metrics alert create --resource-group $ResourceGroup --name alert-vm-memory --scopes (az vm show -g $ResourceGroup -n $VmName --query id -o tsv) --condition 'avg Available Memory Bytes < 1073741824' --window-size 15m --evaluation-frequency 5m --action ag-mclabor-owner --description 'less than 1 GB memory free'",
    "az monitor metrics alert create --resource-group $ResourceGroup --name alert-vm-disk --scopes (az vm show -g $ResourceGroup -n $VmName --query id -o tsv) --condition 'avg OS Disk Queue Depth > 8' --window-size 15m --evaluation-frequency 5m --action ag-mclabor-owner",
    "az monitor metrics alert create --resource-group $ResourceGroup --name alert-vm-availability --scopes (az vm show -g $ResourceGroup -n $VmName --query id -o tsv) --condition 'avg VmAvailabilityMetric < 1' --window-size 5m --evaluation-frequency 1m --action ag-mclabor-owner --description 'the VM is not available'",
    # B-series: when the banked CPU credits run low the VM is throttled to its baseline; this is the signal to resize to the next size
    "az monitor metrics alert create --resource-group $ResourceGroup --name alert-vm-cpu-credits --scopes (az vm show -g $ResourceGroup -n $VmName --query id -o tsv) --condition 'avg CPU Credits Remaining < 100' --window-size 15m --evaluation-frequency 5m --action ag-mclabor-owner --description 'CPU credits nearly used up: searches will slow down; consider resizing the VM'",
    # the backup task and the health check write Error events; the Azure Monitor agent ships Application-log errors to the workspace (small volume, inside the free 5 GB)
    "az vm extension set --resource-group $ResourceGroup --vm-name $VmName --name AzureMonitorWindowsAgent --publisher Microsoft.Azure.Monitor --enable-auto-upgrade true",
    # the data collection rule file is generated from the template with the real workspace id (no placeholder is left in it)
    "`$dcr = Get-Content `"$dcrTemplate`" -Raw | ConvertFrom-Json; `$dcr.location = '$Location'; `$dcr.properties.destinations.logAnalytics[0].workspaceResourceId = (az monitor log-analytics workspace show -g $ResourceGroup -n log-mclabor --query id -o tsv); `$dcr | ConvertTo-Json -Depth 12 | Set-Content `"$dcrGenerated`"",
    "az monitor data-collection rule create --resource-group $ResourceGroup --name dcr-mclabor-events --location $Location --rule-file `"@$dcrGenerated`"",
    "az monitor data-collection rule association create --name dcra-mclabor --rule-id (az monitor data-collection rule show -g $ResourceGroup -n dcr-mclabor-events --query id -o tsv) --resource (az vm show -g $ResourceGroup -n $VmName --query id -o tsv)",
    "az monitor scheduled-query create --resource-group $ResourceGroup --name alert-backup-or-website-error --scopes (az monitor log-analytics workspace show -g $ResourceGroup -n log-mclabor --query id -o tsv) --condition `"count 'Placeholder' > 0`" --condition-query `"Event | where EventLog == 'Application' and Source in ('MCLaborBackup', 'MCLaborWeb') and EventLevelName == 'Error'`" --evaluation-frequency 15m --window-size 15m --action-groups ag-mclabor-owner --description 'backup failed or website not ready'",
    # the budget: 50 / 75 / 90 / 100 % of $BudgetUsd, actual and forecast, e-mailed to the owner
    "az deployment sub create --location $Location --template-file `"$(Join-Path $here 'budget.bicep')`" --parameters amount=$BudgetUsd budgetName=mclabor-monthly-$Environment contactEmails=`"['$AlertEmail']`" resourceGroups=`"['$ResourceGroup']`""
)
Write-Output "Single-VM provisioning plan for $($Environment.ToUpper()) in $Location ($($plan.Count) steps): resource group $ResourceGroup, VM $VmName ($VmSize), budget $BudgetUsd USD$(if ($AutoShutdownTime) { ", auto-shutdown $AutoShutdownTime" })$(if ($SkipVmBackup) { ', no Azure Backup' })."
Write-Output $(if ($Execute) { 'EXECUTING' } else { 'DRY RUN - nothing is created, nothing is paid for' })
$step = 0
foreach ($cmd in $plan) {
    $step++
    Write-Output ""; Write-Output "  [$step/$($plan.Count)] $($cmd -replace '\$AdminPasswordQuoted', '********')"
    if ($Execute) {
        if ($cmd -match '<[^>]+>') { throw "Placeholder still present in: $cmd. Fill it in before executing. Stopped; later steps were not run." }
        $global:LASTEXITCODE = 0
        Invoke-Expression $cmd
        if ($LASTEXITCODE -ne 0) { throw "Step $step failed; later steps were not run. Fix the cause and run again: every step is safe to repeat (existing resources are updated, not duplicated)." }
    }
}
if ($Execute) { Write-Output ""; Write-Output "Provisioned $Environment in $ResourceGroup. Next: temporary-rdp.ps1 -Add, then SETUP.md step 5 on the VM." }
if (-not $Execute) { Write-Output ""; Write-Output "Dry run finished. Verified prices and the monthly total: docs/cloud/08-verified-pricing.md" }
