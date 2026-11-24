# Starts the website against the LIVE database (read-only) on this PC, both parts bound to 127.0.0.1 only.
#   powershell -ExecutionPolicy Bypass -File tools\production\start-production.ps1
# Preconditions it checks: backend\.env exists and selects DATA_SOURCE=production; the production password is in the
# encrypted store; the frontend has been built (frontend\.next). The password is loaded into the backend process
# only. The reverse proxy (deploy\gateway) is the only thing staff PCs talk to; it is started separately.
# Stop: close the two windows, or Stop-Process on the uvicorn / node processes.
$ErrorActionPreference = 'Stop'
$root    = Resolve-Path (Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) '..\..')
$backend = Join-Path $root 'backend'
$front   = Join-Path $root 'frontend'
$node    = "$env:USERPROFILE\tools\node"
$envFile = Join-Path $backend '.env'
$secret  = Join-Path $env:LOCALAPPDATA 'MCLabor\production-mclabor_web_read.dpapi'

if (-not (Test-Path $envFile)) { throw 'backend\.env not found. Copy backend\.env.production.example to backend\.env and fill it in first.' }
$ds = ((Get-Content $envFile | Where-Object { $_ -match '^DATA_SOURCE=' }) -replace '^DATA_SOURCE=', '').Trim()
if ($ds -ne 'production') { throw "backend\.env selects DATA_SOURCE=$ds, not production. Nothing was started." }
if (-not (Test-Path $secret)) { throw 'No stored production password (tools\production\store-db-password.ps1). Nothing was started.' }
if (-not (Test-Path (Join-Path $front '.next\BUILD_ID'))) { throw 'The frontend is not built. Run "npm run build" in frontend first. Nothing was started.' }
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root 'tools\gateway-check.ps1') -EnvFile $envFile | Out-Host
if ($LASTEXITCODE -ne 0) { throw 'gateway-check.ps1 reported problems. Fix them first. Nothing was started.' }

# backend: 4 worker processes, password from the store, read-only (the file says so; the website refuses to start otherwise)
$secure = Get-Content $secret | ConvertTo-SecureString
$pw = (New-Object System.Net.NetworkCredential('', $secure)).Password
Start-Process powershell -ArgumentList '-NoExit', '-Command', "`$env:PRODUCTION_DB_PASSWORD = '$pw'; `$env:ANTHROPIC_API_KEY = ''; Set-Location '$backend'; .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 4 --no-access-log"
$pw = $null
# frontend: the production build, this PC only
Start-Process powershell -ArgumentList '-NoExit', '-Command', "`$env:Path = '$node;' + `$env:Path; Set-Location '$front'; npx next start -p 3000 -H 127.0.0.1"
Start-Sleep -Seconds 8
try { $h = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/health' -TimeoutSec 20; Write-Output "Backend: environment=$($h.environment) access_mode=$($h.access_mode) parser=$($h.ai_mode)" } catch { Write-Warning "Backend not answering yet: $($_.Exception.Message)" }
Write-Output 'Frontend: http://127.0.0.1:3000 (reach it through the reverse proxy from other PCs).'
