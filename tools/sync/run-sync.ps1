# Runs ONE synchronization: office SQL Server (read-only login) -> the cloud website's ingest API. Called by the
# scheduled task (register-sync-task.ps1) and by hand:
#   powershell -ExecutionPolicy Bypass -File tools\sync\run-sync.ps1                 (settings: tools\sync\sync.env)
#   powershell -ExecutionPolicy Bypass -File tools\sync\run-sync.ps1 -DryRun         (read and compare, send nothing)
#   powershell -ExecutionPolicy Bypass -File tools\sync\run-sync.ps1 -Full           (send everything again)
# Secrets come from the DPAPI files written by store-sync-secrets.ps1 and are put into THIS process only.
# The website on this PC (DEMO) is not touched: backend\.env is never read (MCLABOR_ENV_FILE=none).
[CmdletBinding()]
param([string]$EnvFile = '', [switch]$DryRun, [switch]$Full, [switch]$Bootstrap, [switch]$Force, [switch]$AllowMassDelete, [string]$Tables = '', [int]$Limit = 0)
$ErrorActionPreference = 'Stop'
$root = Resolve-Path (Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) '..\..')
$backend = Join-Path $root 'backend'
if (-not $EnvFile) { $EnvFile = Join-Path $root 'tools\sync\sync.env' }
if (-not (Test-Path $EnvFile)) { throw "Settings file not found: $EnvFile (copy sync.env.example to sync.env and edit it)." }
foreach ($line in Get-Content $EnvFile) {
    $t = $line.Trim()
    if (-not $t -or $t.StartsWith('#') -or -not $t.Contains('=')) { continue }
    $k, $v = $t.Split('=', 2)
    [Environment]::SetEnvironmentVariable($k.Trim(), $v.Trim(), 'Process')
}
$environment = "$env:DATA_SOURCE".ToLower()
if ($environment -notin @('staging', 'production')) { throw "sync.env must select DATA_SOURCE=staging or production (it says '$env:DATA_SOURCE')." }
if (-not $env:SYNC_API) { throw 'sync.env must set SYNC_API=https://<the website>.' }
$E = $environment.ToUpper()
$dir = Join-Path $env:LOCALAPPDATA 'MCLabor'
$dbFile = Join-Path $dir "$environment-mclabor_web_read.dpapi"
$syncFile = Join-Path $dir "sync-$environment.dpapi"
foreach ($f in $dbFile, $syncFile) { if (-not (Test-Path $f)) { throw "Secret file missing: $f (run store-sync-secrets.ps1 as this Windows account)." } }

$env:MCLABOR_ENV_FILE = 'none'
$env:ANTHROPIC_API_KEY = ''
$env:SEED_ON_STARTUP = 'false'
[Environment]::SetEnvironmentVariable("${E}_WRITES_ENABLED", 'false', 'Process')
[Environment]::SetEnvironmentVariable("${E}_WRITE_APPROVAL", '', 'Process')
$secureDb = Get-Content $dbFile | ConvertTo-SecureString
[Environment]::SetEnvironmentVariable("${E}_DB_PASSWORD", (New-Object System.Net.NetworkCredential('', $secureDb)).Password, 'Process')
$secrets = (New-Object System.Net.NetworkCredential('', (Get-Content $syncFile | ConvertTo-SecureString))).Password | ConvertFrom-Json
$env:SYNC_API_KEY = $secrets.sync_key
if ($secrets.cf_secret) { $env:CF_ACCESS_CLIENT_SECRET = $secrets.cf_secret }

$stateDir = if ($env:SYNC_STATE_DIR) { $env:SYNC_STATE_DIR } else { Join-Path $env:LOCALAPPDATA 'MCLabor\sync' }
New-Item -ItemType Directory -Force (Join-Path $stateDir 'logs') | Out-Null
$log = Join-Path $stateDir ("logs\sync-" + (Get-Date -Format 'yyyyMMdd') + '.log')
$args = @('-m', 'app.syncagent', 'run', '--api', $env:SYNC_API, '--key-env', 'SYNC_API_KEY', '--state', (Join-Path $stateDir "state-$environment.db"), '--log-file', $log)
if ($env:CF_ACCESS_CLIENT_ID) { $args += @('--cf-client-id', $env:CF_ACCESS_CLIENT_ID) }
if ($DryRun) { $args += '--dry-run' }
if ($Full) { $args += '--full' }
if ($Bootstrap) { $args += '--bootstrap' }
if ($Force) { $args += '--force' }
if ($AllowMassDelete) { $args += '--allow-mass-delete' }
if ($Tables) { $args += @('--tables', $Tables) }
if ($Limit -gt 0) { $args += @('--limit', "$Limit") }
Set-Location $backend
try { & (Join-Path $backend '.venv\Scripts\python.exe') @args; $code = $LASTEXITCODE }
finally {
    foreach ($n in "${E}_DB_PASSWORD", 'SYNC_API_KEY', 'CF_ACCESS_CLIENT_SECRET') { Remove-Item "Env:\$n" -ErrorAction SilentlyContinue }
}
if ($code -eq 2) { Write-Output "SYNC DONE WITH SKIPPED DELETIONS (exit 2): a table shrank implausibly or came back empty. See $log; rerun with -AllowMassDelete only after checking the office database." }
elseif ($code -ne 0) { Write-Output "SYNC FAILED (exit $code). See $log" }
exit $code
