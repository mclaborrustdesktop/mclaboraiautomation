# Azure resources for the MC Labor website, as Azure CLI commands. DRY RUN BY DEFAULT: it prints every command and
# runs none. Nothing is created and nothing is paid for unless -Execute is given AND an Azure sign-in exists.
#   powershell -ExecutionPolicy Bypass -File deploy\cloud\azure\provision.ps1            (prints the plan)
#   powershell -ExecutionPolicy Bypass -File deploy\cloud\azure\provision.ps1 -Execute   (creates resources - needs approval)
# Architecture: docs/cloud/01-cloud-architecture.md (recommended option: SQL Server on an Azure VM + Container Apps).
param(
    [switch]$Execute,
    [string]$Subscription = '<subscription id>',
    [string]$Location = 'eastus',
    [string]$ResourceGroup = 'rg-mclabor-prod',
    [string]$VnetName = 'vnet-mclabor',
    [string]$SqlVmName = 'vm-mclabor-sql',
    [string]$SqlVmSize = 'Standard_D2s_v5',          # 2 vCPU / 8 GB; D4s_v5 if the Access users need more
    [string]$SqlImage = 'MicrosoftSQLServer:sql2022-ws2022:standard-gen2:latest',   # or sqldev / express image
    [string]$ContainerEnv = 'cae-mclabor',
    [string]$Registry = 'crmclabor',
    [string]$KeyVault = 'kv-mclabor',
    [string]$LogWorkspace = 'log-mclabor'
)
$ErrorActionPreference = 'Stop'
$plan = @(
    "az account set --subscription $Subscription",
    "az group create --name $ResourceGroup --location $Location",
    # network: one VNet, a subnet for the SQL VM, a subnet for Container Apps, a gateway subnet for the office VPN
    "az network vnet create --resource-group $ResourceGroup --name $VnetName --address-prefixes 10.20.0.0/16 --subnet-name snet-sql --subnet-prefixes 10.20.1.0/24",
    "az network vnet subnet create --resource-group $ResourceGroup --vnet-name $VnetName --name snet-apps --address-prefixes 10.20.2.0/23",
    "az network vnet subnet create --resource-group $ResourceGroup --vnet-name $VnetName --name GatewaySubnet --address-prefixes 10.20.255.0/27",
    "az network nsg create --resource-group $ResourceGroup --name nsg-sql",
    "az network nsg rule create --resource-group $ResourceGroup --nsg-name nsg-sql --name allow-sql-from-vnet --priority 100 --direction Inbound --access Allow --protocol Tcp --destination-port-ranges 1433 --source-address-prefixes VirtualNetwork",
    "az network nsg rule create --resource-group $ResourceGroup --nsg-name nsg-sql --name deny-sql-from-internet --priority 200 --direction Inbound --access Deny --protocol Tcp --destination-port-ranges 1433 --source-address-prefixes Internet",
    # logs and secrets
    "az monitor log-analytics workspace create --resource-group $ResourceGroup --workspace-name $LogWorkspace",
    "az keyvault create --resource-group $ResourceGroup --name $KeyVault --location $Location --enable-rbac-authorization true",
    # the SQL Server VM: NO public IP; reached from the office through the VPN and from the containers through the VNet
    "az vm create --resource-group $ResourceGroup --name $SqlVmName --image $SqlImage --size $SqlVmSize --vnet-name $VnetName --subnet snet-sql --nsg nsg-sql --public-ip-address '""' --admin-username mcladmin --admin-password '<set at run time, from Key Vault>' --os-disk-size-gb 128 --storage-sku Premium_LRS",
    "az sql vm create --resource-group $ResourceGroup --name $SqlVmName --license-type PAYG --sql-mgmt-type Full --connectivity-type PRIVATE --port 1433",
    "az backup vault create --resource-group $ResourceGroup --name rsv-mclabor --location $Location",
    # office-to-cloud VPN (site-to-site from the office router, or point-to-site for individual PCs)
    "az network public-ip create --resource-group $ResourceGroup --name pip-vpn-mclabor --sku Standard --allocation-method Static",
    "az network vnet-gateway create --resource-group $ResourceGroup --name vgw-mclabor --public-ip-address pip-vpn-mclabor --vnet $VnetName --gateway-type Vpn --vpn-type RouteBased --sku VpnGw1 --no-wait",
    # the website: container registry + Container Apps environment inside the VNet
    "az acr create --resource-group $ResourceGroup --name $Registry --sku Basic",
    "az containerapp env create --resource-group $ResourceGroup --name $ContainerEnv --location $Location --infrastructure-subnet-resource-id (az network vnet subnet show -g $ResourceGroup --vnet-name $VnetName -n snet-apps --query id -o tsv) --internal-only false --logs-workspace-id <workspace customer id> --logs-workspace-key <workspace key>",
    "Copy-Item -Recurse -Force ..\..\..\docs\schema ..\..\..\backend\docs\schema   # the schema export goes into the image (outside the build context otherwise)",
    "az acr build --registry $Registry --image mclabor-backend:latest ..\..\..\backend",
    "az acr build --registry $Registry --image mclabor-frontend:latest ..\..\..\frontend",
    "az containerapp create --resource-group $ResourceGroup --name ca-mclabor-web --environment $ContainerEnv --image $Registry.azurecr.io/mclabor-frontend:latest --ingress external --target-port 3000 --min-replicas 1 --max-replicas 3 --cpu 0.5 --memory 1Gi",
    "az containerapp create --resource-group $ResourceGroup --name ca-mclabor-api --environment $ContainerEnv --image $Registry.azurecr.io/mclabor-backend:latest --ingress internal --target-port 8000 --min-replicas 2 --max-replicas 4 --cpu 1 --memory 2Gi --secrets production-db-password=keyvaultref:... jwt-secret=keyvaultref:...",
    "az containerapp auth microsoft update --resource-group $ResourceGroup --name ca-mclabor-web --client-id <app registration> --client-secret-name microsoft-provider-authentication-secret --tenant-id <tenant> --allowed-audiences api://<app registration>",
    "az containerapp auth update --resource-group $ResourceGroup --name ca-mclabor-web --unauthenticated-client-action RedirectToLoginPage"
)
Write-Output "Azure provisioning plan for MC Labor ($($plan.Count) steps). $(if ($Execute) { 'EXECUTING' } else { 'DRY RUN - nothing is created' })"
foreach ($cmd in $plan) {
    Write-Output ""
    Write-Output "  $cmd"
    if ($Execute) {
        if ($cmd -match '<[^>]+>') { throw "Placeholder still present in: $cmd. Fill it in before executing. Stopped; later steps were not run." }
        Invoke-Expression $cmd
        if ($LASTEXITCODE -ne 0) { throw "Step failed; later steps were not run." }
    }
}
if (-not $Execute) { Write-Output ""; Write-Output "Dry run finished. Estimated monthly cost of this plan: docs/cloud/01-cloud-architecture.md, section 6." }
