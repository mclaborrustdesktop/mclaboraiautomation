# The ONLY inbound rule the staging VM ever gets, and only for a few hours: remote desktop from ONE address (the
# office's public IP) while the VM is being set up (SETUP.md steps 5-8). Removed as soon as the Cloudflare tunnel
# and WARP route work; from then on RDP goes through WARP and this rule must not exist.
#   ./temporary-rdp.ps1 -Add -FromIp 203.0.113.10          (in Cloud Shell; your public IP: https://ifconfig.me)
#   ./temporary-rdp.ps1 -Remove
#   ./temporary-rdp.ps1 -Status
param([switch]$Add, [switch]$Remove, [switch]$Status, [string]$FromIp = '', [string]$ResourceGroup = 'rg-mclabor-staging', [string]$Nsg = 'nsg-mclabor')
$ErrorActionPreference = 'Stop'
$name = 'temporary-rdp-setup'
if ($Add) {
    if ($FromIp -notmatch '^\d{1,3}(\.\d{1,3}){3}$') { throw 'Give -FromIp with the office public IPv4 address (one address, not a range).' }
    az network nsg rule create --resource-group $ResourceGroup --nsg-name $Nsg --name $name --priority 90 --direction Inbound --access Allow --protocol Tcp --source-address-prefixes "$FromIp/32" --destination-port-ranges 3389 --description "temporary set-up access; remove after SETUP.md step 11" | Out-Null
    Write-Output "RDP allowed from $FromIp only. Connect to the VM's PUBLIC IP (az network public-ip show -g $ResourceGroup -n pip-mclabor-outbound --query ipAddress -o tsv). REMOVE this rule when the tunnel works: ./temporary-rdp.ps1 -Remove"
}
elseif ($Remove) {
    az network nsg rule delete --resource-group $ResourceGroup --nsg-name $Nsg --name $name 2>$null | Out-Null
    Write-Output "Rule $name removed. The NSG is back to deny-all inbound."
}
else {
    $r = az network nsg rule show --resource-group $ResourceGroup --nsg-name $Nsg --name $name -o json 2>$null | ConvertFrom-Json
    if ($r) { Write-Output "TEMPORARY RDP RULE IS PRESENT from $($r.sourceAddressPrefix) - remove it when set-up is done." } else { Write-Output 'No temporary rule: inbound is deny-all.' }
}
