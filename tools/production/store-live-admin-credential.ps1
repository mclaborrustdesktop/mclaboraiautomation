# Stores the LIVE server's SQL Server ADMINISTRATOR credential on this PC, encrypted with Windows DPAPI for the Windows
# account that runs it, so that Invoke-LiveAdmin.ps1 can run the reviewed scripts without anyone pasting a password
# into a chat or a command line. Typed once at hidden prompts; never displayed, logged or written in clear.
#
#   powershell -ExecutionPolicy Bypass -File tools\production\store-live-admin-credential.ps1            (store)
#   powershell -ExecutionPolicy Bypass -File tools\production\store-live-admin-credential.ps1 -Remove    (delete when done)
#
# This is a privileged secret: remove it (-Remove) as soon as the live-server steps are finished. It is readable only
# by this Windows account on this PC; a copy of the file is useless elsewhere.
param([switch]$Remove, [switch]$Replace)
$ErrorActionPreference = 'Stop'
$dir = Join-Path $env:LOCALAPPDATA 'MCLabor\production'
$file = Join-Path $dir 'live-admin.dpapi'
if ($Remove) {
    if (Test-Path $file) { Remove-Item $file -Force; Write-Output "Removed $file" } else { Write-Output 'Nothing stored.' }
    exit 0
}
if ((Test-Path $file) -and -not $Replace) { throw "A live administrator credential is already stored ($file). Use -Replace to change it, -Remove to delete it." }
New-Item -ItemType Directory -Force $dir | Out-Null
$login = Read-Host 'SQL Server administrator LOGIN NAME on the live server (for example sa, or the administrator login you use in Management Studio)'
if (-not $login.Trim()) { throw 'No login name given. Nothing stored.' }
$one = Read-Host -AsSecureString "Password of $login (typing is hidden)"
$two = Read-Host -AsSecureString 'Type it again'
$p1 = (New-Object System.Net.NetworkCredential('', $one)).Password
$p2 = (New-Object System.Net.NetworkCredential('', $two)).Password
if ($p1 -ne $p2) { throw 'The two entries do not match. Nothing was stored.' }
if (-not $p1) { throw 'Empty password. Nothing was stored.' }
$payload = @{ login = $login.Trim(); password = $p1 } | ConvertTo-Json -Compress
$p1 = $null; $p2 = $null
ConvertTo-SecureString -String $payload -AsPlainText -Force | ConvertFrom-SecureString | Set-Content -Path $file -Encoding ascii
icacls $file /inheritance:r | Out-Null
icacls $file /grant:r "${env:USERDOMAIN}\${env:USERNAME}:(R,W)" | Out-Null
Write-Output "Stored (encrypted for $env:USERDOMAIN\$env:USERNAME on $env:COMPUTERNAME, owner-only file): $file"
Write-Output 'Next: tools\production\Invoke-LiveAdmin.ps1 -Script backup-status   (read-only). Remove the credential with -Remove when the live-server steps are done.'
