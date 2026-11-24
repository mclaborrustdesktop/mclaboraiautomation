# READ-ONLY pre-flight for Azure Cloud Shell (PowerShell). Creates nothing, costs nothing.
#   ./preflight-cloudshell.ps1 [-Location eastus] [-VmSize Standard_B2ms] [-Offer sql2019-ws2022] [-ResourceGroup rg-mclabor-staging]
# Checks: who is signed in and to which subscription; whether that account may create resources; vCPU quota for the
# B-series in the region; the SQL Server Express image SKUs; whether the VM size is available in the region; the
# current list prices from Microsoft's Retail Prices API; and that the resource group name is free.
param([string]$Location = 'eastus', [string]$VmSize = 'Standard_B2ms', [string]$Offer = 'sql2019-ws2022', [string]$ResourceGroup = 'rg-mclabor-staging')
$ErrorActionPreference = 'Continue'
$fails = 0; $warns = 0
function Pass($m) { Write-Output "  [PASS] $m" }
function Warn($m) { $script:warns++; Write-Output "  [WARN] $m" }
function Fail($m) { $script:fails++; Write-Output "  [FAIL] $m" }

Write-Output "MC Labor staging pre-flight - $(Get-Date -Format 'yyyy-MM-dd HH:mm') - region $Location, size $VmSize"
Write-Output "1. Sign-in and subscription"
$acct = az account show -o json 2>$null | ConvertFrom-Json
if (-not $acct) { Fail 'Not signed in. Run: az login'; Write-Output "RESULT: $fails problem(s)"; exit 1 }
Pass "Signed in as $($acct.user.name) ($($acct.user.type))"
Pass "Subscription: $($acct.name)  id $($acct.id)  state $($acct.state)  tenant $($acct.tenantId)"
$all = az account list --query "[].{name:name,id:id,isDefault:isDefault}" -o json | ConvertFrom-Json
if (($all | Measure-Object).Count -gt 1) { Warn "$(($all | Measure-Object).Count) subscriptions visible; the one above is in use. Change with: az account set --subscription <id>" }
if ($acct.state -ne 'Enabled') { Fail "Subscription state is $($acct.state)" }

Write-Output "2. Permissions"
$roles = az role assignment list --assignee $acct.user.name --scope "/subscriptions/$($acct.id)" --include-inherited --query "[].roleDefinitionName" -o json 2>$null | ConvertFrom-Json
if ($roles -contains 'Owner' -or $roles -contains 'Contributor') { Pass "Role on the subscription: $($roles -join ', ')" }
elseif ($roles) { Warn "Roles: $($roles -join ', '). Contributor on the subscription (or on $ResourceGroup once it exists) is needed to create resources; Owner or 'Cost Management Contributor' for the budget" }
else { Warn 'No role assignment visible for this account at subscription scope (a classic administrator or a group membership may still grant it); the first az group create will tell' }

Write-Output "3. Providers and quota"
foreach ($ns in 'Microsoft.Compute', 'Microsoft.Network', 'Microsoft.Storage', 'Microsoft.SqlVirtualMachine', 'Microsoft.OperationalInsights', 'Microsoft.Insights', 'Microsoft.Consumption') {
    $state = az provider show --namespace $ns --query registrationState -o tsv 2>$null
    if ($state -eq 'Registered') { Pass "$ns registered" } else { Warn "$ns is $state - register with: az provider register --namespace $ns (free, takes a minute)" }
}
$family = if ($VmSize -like 'Standard_B*') { 'standardBSFamily' } else { 'standardDSv5Family' }
$usage = az vm list-usage --location $Location --query "[?name.value=='$family'] | [0]" -o json 2>$null | ConvertFrom-Json
$need = if ($VmSize -eq 'Standard_B2ms') { 2 } elseif ($VmSize -eq 'Standard_B4ms') { 4 } else { 2 }
if ($usage) { if (($usage.limit - $usage.currentValue) -ge $need) { Pass "vCPU quota for $family in ${Location}: $($usage.currentValue) used of $($usage.limit) (need $need)" } else { Fail "vCPU quota for $family in ${Location}: $($usage.currentValue) of $($usage.limit) used; request an increase in the portal (free)" } }
else { Warn "Could not read the vCPU quota for $family" }

Write-Output "4. VM size and image in $Location"
$sku = az vm list-skus --location $Location --size $VmSize --resource-type virtualMachines -o json 2>$null | ConvertFrom-Json | Select-Object -First 1
if ($sku) {
    $restr = @($sku.restrictions | Where-Object { $_.reasonCode })
    if ($restr.Count -eq 0) { Pass "$VmSize is available in $Location (zones: $($sku.locationInfo[0].zones -join ','))" } else { Fail "$VmSize is restricted in ${Location}: $($restr[0].reasonCode). Try eastus2 (same price)" }
} else { Fail "$VmSize not found in $Location" }
$skus = az vm image list-skus --location $Location --publisher MicrosoftSQLServer --offer $Offer --query "[].name" -o json 2>$null | ConvertFrom-Json
if ($skus) {
    $express = @($skus | Where-Object { $_ -like 'express*' })
    if ($express) { Pass "SQL Server Express image SKU(s) for ${Offer}: $($express -join ', ')  -> use -Image MicrosoftSQLServer:${Offer}:$($express[0]):latest" } else { Fail "No Express SKU in offer $Offer (SKUs: $($skus -join ', '))" }
    $img = az vm image show --location $Location --urn "MicrosoftSQLServer:${Offer}:$($express[0]):latest" -o json 2>$null | ConvertFrom-Json
    if ($img) { Pass "Image version $($img.name); plan: $(if ($img.plan) { "$($img.plan.publisher)/$($img.plan.product)/$($img.plan.name) (marketplace terms apply: az vm image terms accept)" } else { 'none (first-party image, no terms to accept)' })" }
} else { Fail "Offer $Offer not found for publisher MicrosoftSQLServer in $Location" }

Write-Output "5. Current list prices (Microsoft Retail Prices API, pay-as-you-go, USD)"
try {
    $f = "armRegionName eq '$Location' and armSkuName eq '$VmSize' and priceType eq 'Consumption' and contains(productName, 'Windows')"
    $p = (Invoke-RestMethod -Uri ("https://prices.azure.com/api/retail/prices?`$filter=" + [uri]::EscapeDataString($f))).Items | Where-Object { $_.productName -like 'Virtual Machines*' -and $_.skuName -notlike '*Spot*' -and $_.skuName -notlike '*Low Priority*' } | Select-Object -First 1
    if ($p) { Pass ("{0} Windows: {1} USD/hour = {2:N2} USD/month at 730 h" -f $VmSize, $p.unitPrice, ($p.unitPrice * 730)) } else { Warn 'VM price not returned' }
    $f2 = "armRegionName eq '$Location' and serviceName eq 'Storage' and productName eq 'Standard SSD Managed Disks' and (skuName eq 'E10 LRS' or skuName eq 'E6 LRS') and contains(meterName, 'Disk')"
    $disks = (Invoke-RestMethod -Uri ("https://prices.azure.com/api/retail/prices?`$filter=" + [uri]::EscapeDataString($f2))).Items | Where-Object { $_.type -eq 'Consumption' }
    foreach ($d in $disks) { Pass ("{0} {1}: {2} USD/month" -f $d.skuName, $d.meterName, $d.unitPrice) }
    $f3 = "armRegionName eq '$Location' and serviceName eq 'Virtual Network' and productName eq 'IP Addresses' and meterName eq 'Standard IPv4 Static Public IP'"
    $ip = (Invoke-RestMethod -Uri ("https://prices.azure.com/api/retail/prices?`$filter=" + [uri]::EscapeDataString($f3))).Items | Where-Object { $_.type -eq 'Consumption' } | Select-Object -First 1
    if ($ip) { Pass ("Standard public IP: {0} USD/hour = {1:N2} USD/month" -f $ip.unitPrice, ($ip.unitPrice * 730)) }
} catch { Warn "Price check failed: $($_.Exception.Message)" }

Write-Output "6. Names"
if ((az group exists --name $ResourceGroup) -eq 'true') { Warn "Resource group $ResourceGroup already exists (the plan updates it in place)" } else { Pass "Resource group name $ResourceGroup is free" }

Write-Output ""
Write-Output "RESULT: $fails problem(s), $warns warning(s). Nothing was created. Paste this output back before provisioning."
exit $(if ($fails) { 1 } else { 0 })
