# Runs the isolated read-only connection check with the stored staging password.
# The password is decrypted in memory, handed to the check through this process only, and never displayed.
$ErrorActionPreference = 'Stop'
$here       = Split-Path -Parent $MyInvocation.MyCommand.Path
$secretFile = Join-Path $env:LOCALAPPDATA 'MCLabor\staging-mclabor_web_read.dpapi'
$python     = Join-Path $here '..\..\backend\.venv\Scripts\python.exe'

if (-not (Test-Path $secretFile)) { throw "No stored password found. Run create-staging-login.ps1 first (needs approval)." }
$secure = Get-Content $secretFile | ConvertTo-SecureString
$env:PRODCHECK_PASSWORD = (New-Object System.Net.NetworkCredential('', $secure)).Password
try { & $python (Join-Path $here 'check_readonly.py'); $code = $LASTEXITCODE }
finally { Remove-Item Env:\PRODCHECK_PASSWORD -ErrorAction SilentlyContinue }
exit $code
