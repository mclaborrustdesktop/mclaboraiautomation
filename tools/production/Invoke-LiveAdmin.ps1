# Runs reviewed scripts against the LIVE SQL Server as its administrator, one PowerShell session at a time.
#
# AUTHENTICATION (default: nothing stored). The administrator login and password are typed at hidden prompts in THIS
# window, kept only in this process, handed to the Python runner through its standard input (not an argument, not an
# environment variable), and discarded when the script ends. Nothing is written to disk. Alternative: -Stored uses the
# DPAPI file written by store-live-admin-credential.ps1 (same hand-off; the file is for the owner's convenience only).
#
#   powershell -ExecutionPolicy Bypass -File tools\production\Invoke-LiveAdmin.ps1 -Scripts backup-status
#   powershell -ExecutionPolicy Bypass -File tools\production\Invoke-LiveAdmin.ps1 -Scripts backup-status,verifyonly
#   powershell -ExecutionPolicy Bypass -File tools\production\Invoke-LiveAdmin.ps1 -Scripts copy-only-backup -Approve copy-only-backup
#
#   backup-status     READ-ONLY  tools\prod-check\backup\0-live-backup-status.sql (nine grids + gate verdict)
#   verifyonly        READ-ONLY  RESTORE VERIFYONLY of the newest full backup file (reads the file; restores nothing)
#   verify-login      READ-ONLY  tools\prod-check\verify-readonly-login.sql (11 grids compared with the expected values)
#   copy-only-backup  CHANGES    tools\prod-check\backup\4-live-copyonly-backup-with-checksum.sql     -> -Approve copy-only-backup
#   readonly-login    CHANGES    tools\prod-check\proposed-grants-production.sql (creates mclabor_web_read; its password is
#                                generated here and stored DPAPI for the website tools and the agent)   -> -Approve readonly-login
#
# Each changing script needs -Approve <its own name> on that very command line; the runner refuses otherwise, refuses a
# server that does not report the expected instance name, refuses a script whose text differs from the reviewed version
# (SHA-256), and refuses a login that lacks the permissions the script needs (pre-flight). Nothing restores, drops or
# replaces a database. Every run writes a report and a log line to %LOCALAPPDATA%\MCLabor\production\reports (no secrets).
param(
    [Parameter(Mandatory = $true)][ValidateSet('backup-status', 'verify-login', 'verifyonly', 'copy-only-backup', 'readonly-login')][string[]]$Scripts,
    [ValidateSet('', 'copy-only-backup', 'readonly-login')][string]$Approve = '',
    [switch]$Stored,
    [string]$Server = ''
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$python = Join-Path $repo 'backend\.venv\Scripts\python.exe'
$runner = Join-Path $repo 'tools\prod-check\live_admin.py'
$hostsFile = Join-Path $repo 'backend\office-hosts.txt'
$hostList = @(Get-Content $hostsFile | Where-Object { $_ -and -not $_.StartsWith('#') } | ForEach-Object { $_.Trim() })
if (-not $Server) { $Server = "tcp:$($hostList[0]),1433" }
$expected = "$($hostList[0])\SQLEXPRESS"

$changing = @($Scripts | Where-Object { $_ -in @('copy-only-backup', 'readonly-login') })
if ($changing.Count -gt 1) { throw 'One changing script per command, each with its own -Approve.' }
if ($changing.Count -eq 1 -and $Approve -ne $changing[0]) { throw "'$($changing[0])' changes the live server. Re-run with -Approve $($changing[0]) only after the owner's explicit approval of that operation." }

# ---- credential: prompted (default) or the DPAPI file; lives in this process only
if ($Stored) {
    $credFile = Join-Path $env:LOCALAPPDATA 'MCLabor\production\live-admin.dpapi'
    if (-not (Test-Path $credFile)) { throw "No stored credential ($credFile). Run without -Stored to be prompted, or store-live-admin-credential.ps1 first." }
    $b = [Runtime.InteropServices.Marshal]::SecureStringToBSTR((Get-Content $credFile | ConvertTo-SecureString))
    try { $cred = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($b) | ConvertFrom-Json } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($b) }
    $login = $cred.login; $password = $cred.password; $cred = $null
} else {
    $login = Read-Host 'SQL Server administrator LOGIN NAME on the live server'
    $sec = Read-Host -AsSecureString "Password of $login (typing is hidden; used in this window only, not stored)"
    $password = (New-Object System.Net.NetworkCredential('', $sec)).Password
    if (-not $login.Trim() -or -not $password) { throw 'Login or password empty. Nothing was run.' }
}

$roPassword = ''
if ($Scripts -contains 'readonly-login') {
    # the read-only login's password: generated here, stored DPAPI in the file the website tools and the sync agent read
    $roFile = Join-Path $env:LOCALAPPDATA 'MCLabor\production-mclabor_web_read.dpapi'
    if (Test-Path $roFile) {
        Write-Output "Using the already stored password for mclabor_web_read ($roFile)."
        $roSec = Get-Content $roFile | ConvertTo-SecureString
    } else {
        $bytes = New-Object byte[] 24
        [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
        $roSec = ConvertTo-SecureString ([Convert]::ToBase64String($bytes).TrimEnd('=')) -AsPlainText -Force
        ConvertFrom-SecureString $roSec | Set-Content -Path $roFile -Encoding ascii
        icacls $roFile /inheritance:r | Out-Null
        icacls $roFile /grant:r "${env:USERDOMAIN}\${env:USERNAME}:(R,W)" | Out-Null
        Write-Output "Generated a 32-character password for mclabor_web_read and stored it DPAPI (owner-only): $roFile"
    }
    $roPassword = (New-Object System.Net.NetworkCredential('', $roSec)).Password
}

$json = @{ login = $login.Trim(); password = $password; readonly_login_password = $roPassword } | ConvertTo-Json -Compress
$worst = 0
try {
    foreach ($s in $Scripts) {
        Write-Output "=== $s ==="
        $args = @('-I', $runner, '--server', $Server, '--expect', $expected, '--mode', $s)
        if ($s -eq $Approve) { $args += @('--approve', $Approve) }
        $json | & $python @args
        if ($LASTEXITCODE -ne 0) { $worst = $LASTEXITCODE; Write-Output "($s ended with code $LASTEXITCODE; later scripts are skipped)"; break }
    }
} finally {
    $json = $null; $password = $null; $roPassword = $null; $login = $null
    [GC]::Collect()
}
exit $worst
