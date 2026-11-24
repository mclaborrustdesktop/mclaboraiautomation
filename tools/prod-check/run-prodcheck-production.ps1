# Runs the isolated read-only connection check against the LIVE server with the stored production password.
#   powershell -ExecutionPolicy Bypass -File tools\prod-check\run-prodcheck-production.ps1
# Uses tools\prod-check\prodcheck.env.production (copy prodcheck.env.production.example and confirm the server name).
# Reads metadata only: no table row is read. The password is decrypted in memory for this process and never shown.
$ErrorActionPreference = 'Stop'
$here       = Split-Path -Parent $MyInvocation.MyCommand.Path
$secretFile = Join-Path $env:LOCALAPPDATA 'MCLabor\production-mclabor_web_read.dpapi'
$python     = Join-Path $here '..\..\backend\.venv\Scripts\python.exe'
$config     = Join-Path $here 'prodcheck.env.production'
if (-not (Test-Path $config)) { throw "Copy prodcheck.env.production.example to prodcheck.env.production and fill in the confirmed server name first." }
if (-not (Test-Path $secretFile)) { throw "No stored production password. Run tools\production\store-db-password.ps1 first." }
$secure = Get-Content $secretFile | ConvertTo-SecureString
$env:PRODCHECK_PASSWORD = (New-Object System.Net.NetworkCredential('', $secure)).Password
try { & $python (Join-Path $here 'check_readonly.py') --config $config; $code = $LASTEXITCODE }
finally { Remove-Item Env:\PRODCHECK_PASSWORD -ErrorAction SilentlyContinue }
exit $code
