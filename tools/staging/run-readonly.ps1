# Runs ONE backend command against a SQL Server environment (STAGING copy or, once approved, PRODUCTION), read-only,
# WITHOUT switching the website's environment.
#   powershell -File tools\staging\run-readonly.ps1 ..\tools\staging\search_timing.py baseline          (staging: backend\.env.off)
#   powershell -File tools\staging\run-readonly.ps1 -EnvFile backend\.env.production ..\tools\staging\contact_check.py
#   powershell -File tools\staging\run-readonly.ps1 -m app.livecheck
#
# Difference from run-in-staging.ps1: that script needs backend\.env to select staging (which switches the whole
# website). This one loads the settings from the file given (default backend\.env.off) into THIS process only, so
# the website keeps running in DEMO. The database password comes from the Windows-protected store for that
# environment (%LOCALAPPDATA%\MCLabor\<environment>-mclabor_web_read.dpapi, written by create-staging-login.ps1 or
# tools\production\store-db-password.ps1) and is never displayed or written. The engine's statement guard and
# identity check still apply (SELECT only, the one expected server only). Writes are forced off.
[CmdletBinding(PositionalBinding = $false)]
param(
    [string]$EnvFile = '',
    [Parameter(Position = 0, ValueFromRemainingArguments = $true)][string[]]$Rest
)
$ErrorActionPreference = 'Stop'
$root       = Resolve-Path (Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) '..\..')
$backend    = Join-Path $root 'backend'
if (-not $EnvFile) { $EnvFile = Join-Path $backend '.env.off' }
if (-not (Test-Path $EnvFile)) { throw "Settings file not found: $EnvFile" }

# Load KEY=VALUE lines into this process only (comments and blanks skipped). Nothing is written to disk.
foreach ($line in Get-Content $EnvFile) {
    $t = $line.Trim()
    if (-not $t -or $t.StartsWith('#') -or -not $t.Contains('=')) { continue }
    $k, $v = $t.Split('=', 2)
    [Environment]::SetEnvironmentVariable($k.Trim(), $v.Trim(), 'Process')
}
$environment = "$env:DATA_SOURCE".ToLower()
if ($environment -notin @('staging', 'production')) { throw "The settings file must select DATA_SOURCE=staging or production (it says '$env:DATA_SOURCE'). Nothing was run." }
$secretFile = Join-Path $env:LOCALAPPDATA "MCLabor\$environment-mclabor_web_read.dpapi"
if (-not (Test-Path $secretFile)) { throw "No stored $environment password found ($secretFile)." }

$env:MCLABOR_ENV_FILE = 'none'          # never read backend\.env (there must be none while the website is in DEMO)
$env:ANTHROPIC_API_KEY = ''             # no outside AI service against real data
$env:SEED_ON_STARTUP = 'false'
$E = $environment.ToUpper()
[Environment]::SetEnvironmentVariable("${E}_WRITES_ENABLED", 'false', 'Process')
[Environment]::SetEnvironmentVariable("${E}_WRITE_APPROVAL", '', 'Process')
$secure = Get-Content $secretFile | ConvertTo-SecureString
[Environment]::SetEnvironmentVariable("${E}_DB_PASSWORD", (New-Object System.Net.NetworkCredential('', $secure)).Password, 'Process')
Set-Location $backend
try { & (Join-Path $backend '.venv\Scripts\python.exe') @Rest; $code = $LASTEXITCODE }
finally { Remove-Item "Env:\${E}_DB_PASSWORD" -ErrorAction SilentlyContinue }
exit $code
