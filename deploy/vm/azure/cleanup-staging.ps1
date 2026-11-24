# Removes the STAGING environment completely (everything in its resource group) so that nothing keeps billing.
#   powershell -ExecutionPolicy Bypass -File deploy\vm\azure\cleanup-staging.ps1                      (shows what would be deleted)
#   powershell -ExecutionPolicy Bypass -File deploy\vm\azure\cleanup-staging.ps1 -Execute             (deletes, after typing the group name)
# Also: -DeallocateOnly stops the VM's compute billing but keeps everything (disks and IP keep billing, about 21 USD/month).
# Synthetic data only lives there, so nothing is lost; the budget and the Cloudflare tunnel entry are removed separately.
param([string]$ResourceGroup = 'rg-mclabor-staging', [string]$VmName = 'vm-mclabor-stg', [switch]$Execute, [switch]$DeallocateOnly)
$ErrorActionPreference = 'Stop'
if (-not (Get-Command az -ErrorAction SilentlyContinue)) { throw 'Azure CLI (az) is not installed on this PC.' }
$tags = az group show --name $ResourceGroup --query tags -o json 2>$null | ConvertFrom-Json
if (-not $tags) { throw "Resource group $ResourceGroup not found (or not signed in)." }
if ($tags.environment -ne 'staging' -or $tags.data -ne 'synthetic-only') { throw "Refusing: $ResourceGroup is not tagged environment=staging data=synthetic-only. Nothing was deleted." }
Write-Output "Resources in $ResourceGroup (tags: environment=$($tags.environment), data=$($tags.data)):"
az resource list --resource-group $ResourceGroup --query "[].{name:name, type:type}" -o table
if ($DeallocateOnly) {
    if ($Execute) { az vm deallocate --resource-group $ResourceGroup --name $VmName; Write-Output "$VmName deallocated: compute billing stopped; disks, IP and storage keep billing." }
    else { Write-Output "Dry run: would deallocate $VmName (add -Execute)." }
    exit 0
}
if (-not $Execute) { Write-Output "Dry run: would delete the whole resource group $ResourceGroup and everything above (add -Execute)."; exit 0 }
$typed = Read-Host "Type the resource group name to confirm deletion"
if ($typed -ne $ResourceGroup) { throw 'Name did not match. Nothing was deleted.' }
az group delete --name $ResourceGroup --yes
az consumption budget delete --budget-name mclabor-monthly-staging 2>$null | Out-Null
Write-Output "Deleted $ResourceGroup. Remaining manual steps: remove the tunnel and the staging hostname in the Cloudflare dashboard (free, no cost either way)."
