# Runs one backend command with the staging database password loaded from the encrypted store.
#   powershell -File tools\staging\run-in-staging.ps1 -m app.livecheck
#   powershell -File tools\staging\run-in-staging.ps1 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# The password is decrypted in memory for this process only. It is never displayed or written to a file.
# backend\.env must select DATA_SOURCE=staging (it holds no database password).
$ErrorActionPreference = 'Stop'
$root       = Resolve-Path (Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) '..\..')
$backend    = Join-Path $root 'backend'
$secretFile = Join-Path $env:LOCALAPPDATA 'MCLabor\staging-mclabor_web_read.dpapi'

if (-not (Test-Path (Join-Path $backend '.env'))) { throw "backend\.env not found: the website is in DEMO. Nothing was run." }
if (-not (Test-Path $secretFile)) { throw "No stored staging password found." }
$secure = Get-Content $secretFile | ConvertTo-SecureString
$env:STAGING_DB_PASSWORD = (New-Object System.Net.NetworkCredential('', $secure)).Password
$env:ANTHROPIC_API_KEY = ''      # staging never calls an outside AI service
$env:SEED_ON_STARTUP = 'false'
Set-Location $backend
try { & (Join-Path $backend '.venv\Scripts\python.exe') @args; $code = $LASTEXITCODE }
finally { Remove-Item Env:\STAGING_DB_PASSWORD -ErrorAction SilentlyContinue }
exit $code
