# Run ON THE VM as administrator. Installs or updates ONE environment of the website from a copy of this repository.
#   powershell -ExecutionPolicy Bypass -File deploy-app.ps1 -Environment production -Source C:\mclabor\downloads\mclabor-src.zip
#   powershell -ExecutionPolicy Bypass -File deploy-app.ps1 -Environment staging -Source \\share\mclabor-src
# Layout: C:\mclabor\<environment>\app (the code), \backend.env (settings, kept on update), \secrets (files the
# service account alone can read), \data (web sign-in store), \logs. Services: mclabor-<environment>-backend and
# -frontend, run by NSSM under virtual service accounts, started automatically, stdout/stderr rotated in \logs.
# Ports: production 8000/3000, staging 8100/3100, bound to 127.0.0.1 only. The tunnel reaches them; nothing else does.
#Requires -RunAsAdministrator
param(
    [Parameter(Mandatory = $true)][ValidateSet('production', 'staging')][string]$Environment,
    [Parameter(Mandatory = $true)][string]$Source,
    [string]$Root = 'C:\mclabor'
)
$ErrorActionPreference = 'Stop'
$ports = @{ production = @{ api = 8000; web = 3000 }; staging = @{ api = 8100; web = 3100 } }[$Environment]
$home_ = Join-Path $Root $Environment
$app = Join-Path $home_ 'app'
$nssm = Join-Path $Root 'tools\nssm.exe'
if (-not (Test-Path $nssm)) { throw 'NSSM not found: run install-prerequisites.ps1 first.' }
foreach ($d in $home_, "$home_\secrets", "$home_\data", "$home_\logs") { New-Item -ItemType Directory -Force $d | Out-Null }

# 1. the code: unpack or copy; keep the previous version for a quick rollback
if (Test-Path $app) { $prev = "$app.previous"; if (Test-Path $prev) { Remove-Item $prev -Recurse -Force }; Rename-Item $app $prev }
New-Item -ItemType Directory -Force $app | Out-Null
if ($Source -like '*.zip') { Expand-Archive $Source -DestinationPath $app -Force } else { Copy-Item "$Source\*" $app -Recurse -Force }
foreach ($junk in 'backend\.venv', 'backend\.env', 'backend\*.db', 'frontend\node_modules', 'frontend\.next', 'frontend\.env.local') { Remove-Item (Join-Path $app $junk) -Recurse -Force -ErrorAction SilentlyContinue }

# 2. backend: its own Python environment
& py -3.12 -m venv "$app\backend\.venv"
& "$app\backend\.venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
& "$app\backend\.venv\Scripts\python.exe" -m pip install --quiet -r "$app\backend\requirements.txt"

# 3. frontend: production build, API on the same address (empty NEXT_PUBLIC_API_URL), standalone output
Push-Location "$app\frontend"
try {
    $env:NEXT_PUBLIC_API_URL = ''; $env:NEXT_TELEMETRY_DISABLED = '1'
    & npm ci --no-audit --no-fund | Out-Null
    & npm run build | Out-Null
    Copy-Item .\public .\.next\standalone\public -Recurse -Force
    Copy-Item .\.next\static .\.next\standalone\.next\static -Recurse -Force
}
finally { Pop-Location }

# 4. settings: from the template on first install only; secrets folder locked to the service accounts
$envFile = Join-Path $home_ 'backend.env'
if (-not (Test-Path $envFile)) {
    Copy-Item "$app\deploy\vm\env\backend.$Environment.env.example" $envFile
    Write-Warning "First install: edit $envFile (server name, Cloudflare team domain and AUD, access lists) before starting the backend."
}
$svcApi = "mclabor-$Environment-backend"; $svcWeb = "mclabor-$Environment-frontend"
foreach ($svc in $svcApi, $svcWeb) { if (Get-Service $svc -ErrorAction SilentlyContinue) { & $nssm stop $svc | Out-Null } }
$acl = Get-Acl "$home_\secrets"; $acl.SetAccessRuleProtection($true, $false)
foreach ($id in 'BUILTIN\Administrators', 'NT AUTHORITY\SYSTEM', "NT SERVICE\$svcApi") {
    $acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule($id, 'Read', 'ContainerInherit,ObjectInherit', 'None', 'Allow')))
}
$acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule('BUILTIN\Administrators', 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')))
Set-Acl "$home_\secrets" $acl
foreach ($f in 'jwt_secret') {
    $p = Join-Path "$home_\secrets" $f
    if (-not (Test-Path $p)) { [IO.File]::WriteAllText($p, (& "$app\backend\.venv\Scripts\python.exe" -c "import secrets;print(secrets.token_urlsafe(48), end='')")) }
}
$dbSecret = Join-Path "$home_\secrets" "${Environment}_db_password"
if (-not (Test-Path $dbSecret)) { Write-Warning "Put the password of mclabor_web_read (no newline) in $dbSecret before starting the backend." }

# 5. services (NSSM): backend and frontend, virtual service accounts, automatic start, log rotation
function Register-Svc([string]$name, [string]$exe, [string]$args_, [string]$dir, [hashtable]$envs) {
    if (-not (Get-Service $name -ErrorAction SilentlyContinue)) { & $nssm install $name $exe | Out-Null }
    & $nssm set $name Application $exe | Out-Null
    & $nssm set $name AppParameters $args_ | Out-Null
    & $nssm set $name AppDirectory $dir | Out-Null
    & $nssm set $name AppStdout "$home_\logs\$name.log" | Out-Null
    & $nssm set $name AppStderr "$home_\logs\$name.err.log" | Out-Null
    & $nssm set $name AppRotateFiles 1 | Out-Null; & $nssm set $name AppRotateBytes 10485760 | Out-Null; & $nssm set $name AppRotateOnline 1 | Out-Null
    & $nssm set $name AppExit Default Restart | Out-Null; & $nssm set $name AppRestartDelay 5000 | Out-Null
    & $nssm set $name Start SERVICE_AUTO_START | Out-Null
    & $nssm set $name AppEnvironmentExtra ($envs.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) | Out-Null
    & sc.exe config $name obj= "NT SERVICE\$name" | Out-Null
}
Register-Svc $svcApi "$app\backend\.venv\Scripts\python.exe" "-m uvicorn app.main:app --host 127.0.0.1 --port $($ports.api) --workers 4 --no-access-log" "$app\backend" @{
    MCLABOR_ENV_FILE = 'none'; MCLABOR_SETTINGS_FILE = $envFile; MCLABOR_SECRETS_DIR = "$home_\secrets"; PYTHONUNBUFFERED = '1' }
Register-Svc $svcWeb (Get-Command node).Source "server.js" "$app\frontend\.next\standalone" @{ PORT = "$($ports.web)"; HOSTNAME = '127.0.0.1'; NODE_ENV = 'production' }
# the services' accounts need to read the code and write their data and logs
foreach ($pair in @(@($svcApi, $app), @($svcApi, "$home_\data"), @($svcApi, "$home_\logs"), @($svcWeb, "$app\frontend"), @($svcWeb, "$home_\logs"))) {
    $svc, $path = $pair
    $right = if ($path -like '*\data' -or $path -like '*\logs') { 'Modify' } else { 'ReadAndExecute' }
    $a = Get-Acl $path; $a.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule("NT SERVICE\$svc", $right, 'ContainerInherit,ObjectInherit', 'None', 'Allow'))); Set-Acl $path $a
}
# the backend reads its settings from the env file through a wrapper env var (see backend/app/config.py: MCLABOR_SETTINGS_FILE)
& $nssm start $svcWeb | Out-Null
if ((Test-Path $dbSecret) -and (Get-Content $envFile | Where-Object { $_ -match '^CLOUDFLARE_ACCESS_AUD=.+' -and $_ -notmatch '<' })) { & $nssm start $svcApi | Out-Null } else { Write-Warning "Backend not started: settings or password still missing (see warnings above). Start it with: nssm start $svcApi" }
Start-Sleep -Seconds 8
try { $h = Invoke-RestMethod -Uri "http://127.0.0.1:$($ports.api)/api/health" -TimeoutSec 10; Write-Output "backend ${Environment}: environment=$($h.environment) access_mode=$($h.access_mode) parser=$($h.ai_mode)" } catch { Write-Warning "backend not answering yet ($($_.Exception.Message)); see $home_\logs\$svcApi.err.log" }
try { Invoke-RestMethod -Uri "http://127.0.0.1:$($ports.web)/healthz" -TimeoutSec 10 | Out-Null; Write-Output "frontend ${Environment}: ok on 127.0.0.1:$($ports.web)" } catch { Write-Warning "frontend not answering yet ($($_.Exception.Message))" }
Write-Output "Deployed $Environment from $Source into $app (previous version kept in $app.previous)."
