# Runs ONE reviewed script against the LIVE SQL Server with the stored administrator credential (store-live-admin-credential.ps1).
# The credential is decrypted into this process only and handed to the Python runner through its environment; it is
# never printed, never written. Every run appends to %LOCALAPPDATA%\MCLabor\production\reports\live-admin-log.md and
# writes a full report file there (grids as tables, no secrets).
#
#   -Script backup-status     READ-ONLY  tools\prod-check\backup\0-live-backup-status.sql (nine grids + gate verdict)
#   -Script verify-login      READ-ONLY  tools\prod-check\verify-readonly-login.sql (11 grids compared with the expected values)
#   -Script verifyonly        READ-ONLY  RESTORE VERIFYONLY of the newest full backup file (reads the file; restores nothing)
#   -Script copy-only-backup  CHANGES    tools\prod-check\backup\4-live-copyonly-backup-with-checksum.sql  -> needs -Approve
#   -Script readonly-login    CHANGES    tools\prod-check\proposed-grants-production.sql (creates mclabor_web_read; the login's
#                                        password is generated here and stored DPAPI for the website tools and the agent) -> needs -Approve
#
# Server: the first host of backend\office-hosts.txt on the fixed port 1433 (the Browser service is off). The runner
# refuses to continue if the server does not report the expected instance name, and never runs a changing script
# without -Approve. Nothing here restores, drops or replaces a database.
param(
    [Parameter(Mandatory = $true)][ValidateSet('backup-status', 'verify-login', 'verifyonly', 'copy-only-backup', 'readonly-login')][string]$Script,
    [switch]$Approve,
    [string]$Server = ''
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$dir = Join-Path $env:LOCALAPPDATA 'MCLabor\production'
$credFile = Join-Path $dir 'live-admin.dpapi'
if (-not (Test-Path $credFile)) { throw "No live administrator credential stored. Run tools\production\store-live-admin-credential.ps1 first (hidden prompt, nothing in chat)." }
$hostsFile = Join-Path $repo 'backend\office-hosts.txt'
$hostList = @(Get-Content $hostsFile | Where-Object { $_ -and -not $_.StartsWith('#') } | ForEach-Object { $_.Trim() })
if (-not $Server) { $Server = "tcp:$($hostList[0]),1433" }
$expected = "$($hostList[0])\SQLEXPRESS"

$changing = $Script -in @('copy-only-backup', 'readonly-login')
if ($changing -and -not $Approve) { throw "'$Script' changes the live server. Re-run with -Approve only after the owner's explicit approval." }

$payload = Get-Content $credFile | ConvertTo-SecureString
$b = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($payload)
try { $json = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($b) | ConvertFrom-Json } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($b) }
$env:LIVE_ADMIN_LOGIN = $json.login
$env:LIVE_ADMIN_PASSWORD = $json.password
$json = $null

if ($Script -eq 'readonly-login') {
    # the read-only login's password: generated here, stored DPAPI in the file the website tools and the sync agent read
    $roFile = Join-Path $env:LOCALAPPDATA 'MCLabor\production-mclabor_web_read.dpapi'
    if (Test-Path $roFile) {
        Write-Output "Using the already stored password for mclabor_web_read ($roFile)."
        $sec = Get-Content $roFile | ConvertTo-SecureString
    } else {
        $bytes = New-Object byte[] 24
        [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
        $sec = ConvertTo-SecureString ([Convert]::ToBase64String($bytes).TrimEnd('=')) -AsPlainText -Force
        ConvertFrom-SecureString $sec | Set-Content -Path $roFile -Encoding ascii
        Write-Output "Generated a 32-character password for mclabor_web_read and stored it DPAPI: $roFile"
    }
    $env:READONLY_LOGIN_PASSWORD = (New-Object System.Net.NetworkCredential('', $sec)).Password
}

try {
    & (Join-Path $repo 'backend\.venv\Scripts\python.exe') -I (Join-Path $repo 'tools\prod-check\live_admin.py') --server $Server --expect $expected --mode $Script $(if ($Approve) { '--approve' })
    $code = $LASTEXITCODE
} finally {
    Remove-Item Env:LIVE_ADMIN_LOGIN, Env:LIVE_ADMIN_PASSWORD, Env:READONLY_LOGIN_PASSWORD -ErrorAction SilentlyContinue
}
exit $code
