# Run ON THE VM as administrator. Windows Firewall: nothing comes in except SQL Server (and remote desktop for
# administrators) from the Cloudflare WARP address range and the VM's own subnet. The Azure network security group
# blocks everything from the internet before it even reaches Windows; this is the second layer.
#   powershell -ExecutionPolicy Bypass -File firewall.ps1 [-WarpRange 100.96.0.0/12] [-Subnet 10.20.1.0/24]
#Requires -RunAsAdministrator
param([string]$WarpRange = '100.96.0.0/12', [string]$Subnet = '10.20.1.0/24')
$ErrorActionPreference = 'Stop'
Set-NetFirewallProfile -Profile Domain, Private, Public -DefaultInboundAction Block -DefaultOutboundAction Allow -Enabled True
foreach ($r in Get-NetFirewallRule -DisplayName 'MC Labor *' -ErrorAction SilentlyContinue) { Remove-NetFirewallRule -Name $r.Name }
New-NetFirewallRule -DisplayName 'MC Labor SQL Server from tunnel and subnet' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 1433 -RemoteAddress $WarpRange, $Subnet -Profile Any | Out-Null
New-NetFirewallRule -DisplayName 'MC Labor remote desktop from tunnel only' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 3389 -RemoteAddress $WarpRange -Profile Any | Out-Null
# the website's own ports are bound to 127.0.0.1 and need no rule; make sure no earlier rule opened them
foreach ($port in 8000, 3000, 8100, 3100) {
    foreach ($r in Get-NetFirewallPortFilter | Where-Object { $_.LocalPort -eq "$port" } | Get-NetFirewallRule | Where-Object { $_.Direction -eq 'Inbound' -and $_.Action -eq 'Allow' }) { Disable-NetFirewallRule -Name $r.Name }
}
# the built-in "Remote Desktop" rules allow 3389 from anywhere: off, the rule above replaces them
Get-NetFirewallRule -DisplayGroup 'Remote Desktop' -ErrorAction SilentlyContinue | Disable-NetFirewallRule
Write-Output 'Inbound: blocked by default; SQL 1433 from the WARP range and the subnet; RDP 3389 from the WARP range only. Nothing else.'
Get-NetFirewallRule -DisplayName 'MC Labor *' | Select-Object DisplayName, Enabled, Action | Format-Table -AutoSize
