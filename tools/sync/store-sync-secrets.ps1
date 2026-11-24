# Stores the two secrets the office sync agent needs, encrypted with Windows DPAPI for the account that runs it:
#   - the read-only SQL login's password (production-mclabor_web_read.dpapi, same file the website's tools use)
#   - the cloud sync key and the Cloudflare service token secret (sync-<env>.dpapi)
# Typed once at hidden prompts; never displayed, logged or written in clear. Run it AS the Windows account of the
# scheduled task (register-sync-task.ps1), because DPAPI ties the files to that account.
#   powershell -ExecutionPolicy Bypass -File tools\sync\store-sync-secrets.ps1 -Environment production
param([ValidateSet('production', 'staging')][string]$Environment = 'production', [switch]$Replace)
$ErrorActionPreference = 'Stop'
$dir = Join-Path $env:LOCALAPPDATA 'MCLabor'
New-Item -ItemType Directory -Force $dir | Out-Null
$dbFile = Join-Path $dir "$Environment-mclabor_web_read.dpapi"
$syncFile = Join-Path $dir "sync-$Environment.dpapi"

if ((Test-Path $dbFile) -and -not $Replace) {
    Write-Output "SQL password already stored ($dbFile); kept. Use -Replace to change it."
} else {
    $one = Read-Host -AsSecureString "Password of SQL login mclabor_web_read on the $Environment server (hidden)"
    $two = Read-Host -AsSecureString 'Type it again'
    if ((New-Object System.Net.NetworkCredential('', $one)).Password -ne (New-Object System.Net.NetworkCredential('', $two)).Password) { throw 'The two entries do not match. Nothing stored.' }
    ConvertFrom-SecureString $one | Set-Content -Path $dbFile -Encoding ascii
    Write-Output "Stored: $dbFile"
}
if ((Test-Path $syncFile) -and -not $Replace) {
    Write-Output "Sync secrets already stored ($syncFile); kept. Use -Replace to change them."
} else {
    $key = Read-Host -AsSecureString 'Cloud SYNC_API_KEY (32+ characters, the same value sealed in Railway; hidden)'
    if ((New-Object System.Net.NetworkCredential('', $key)).Password.Length -lt 32) { throw 'The sync key must be at least 32 characters. Nothing stored.' }
    $cf = Read-Host -AsSecureString 'Cloudflare service token SECRET (empty if the website is not behind Cloudflare Access; hidden)'
    $payload = @{ sync_key = (New-Object System.Net.NetworkCredential('', $key)).Password; cf_secret = (New-Object System.Net.NetworkCredential('', $cf)).Password } | ConvertTo-Json -Compress
    ConvertTo-SecureString -String $payload -AsPlainText -Force | ConvertFrom-SecureString | Set-Content -Path $syncFile -Encoding ascii
    Write-Output "Stored: $syncFile"
}
Write-Output "Encrypted for $env:USERDOMAIN\$env:USERNAME on $env:COMPUTERNAME. Next: register-sync-task.ps1, then run-sync.ps1 -Once to test."
