# Builds the PRODUCTION variable files from the locally generated secrets, then verifies them with the backend's own
# rules. Creates nothing in the cloud. Output (owner-only permissions, never committed):
#   %LOCALAPPDATA%\MCLabor\production\backend.production.variables.env   -> Railway backend service variables
#   %LOCALAPPDATA%\MCLabor\production\frontend.production.variables.env  -> Railway frontend service variables
#   %LOCALAPPDATA%\MCLabor\production\sync.env                           -> tools\sync\sync.env on the office PC that runs the agent
# Inputs: railway-production-secrets.json (label, site_hash, jwt, sync) written on 2026-11-26, site-password-production.dpapi,
#         backend\office-hosts.txt (the office servers), and the parameters below.
#
#   powershell -ExecutionPolicy Bypass -File tools\railway\Build-ProductionVariables.ps1 -DefaultUser RAY -Admins RAY -SiteUrl https://<production host>
#
# -DefaultUser: initials of the staff record everyone acts as behind the single password (must exist and be active in tblOfficeStaff).
# -Admins:      initials (or e-mails) allowed to see the Users page, the status page and the unlock log. Because everyone shares
#               one identity, listing -DefaultUser here means every password holder sees those read-only pages; leaving it out
#               means nobody does (the operator reads the log with the command line). Decide with the client.
# -SiteUrl:     the production website address once the Railway domain exists (leave the placeholder until then).
param(
    [Parameter(Mandatory = $true)][string]$DefaultUser,
    [string]$Admins = '',
    [string]$SiteUrl = 'https://<production-host>',
    [string]$Server = '',   # default: the first host in backend\office-hosts.txt + \SQLEXPRESS (the live server)
    [string]$Database = 'McLabor'
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$dir = Join-Path $env:LOCALAPPDATA 'MCLabor\production'
$secretsFile = Join-Path $dir 'railway-production-secrets.json'
$dpapiFile = Join-Path $dir 'site-password-production.dpapi'
$hostsFile = Join-Path $repo 'backend\office-hosts.txt'
foreach ($f in @($secretsFile, $dpapiFile, $hostsFile)) { if (-not (Test-Path $f)) { throw "Missing: $f" } }

$s = Get-Content $secretsFile -Raw | ConvertFrom-Json
foreach ($k in 'label', 'site_hash', 'jwt', 'sync') { if (-not $s.$k) { throw "railway-production-secrets.json has no '$k'" } }
$hostList = @(Get-Content $hostsFile | Where-Object { $_ -and -not $_.StartsWith('#') } | ForEach-Object { $_.Trim() })
$hosts = $hostList -join ','
if (-not $Server) { $Server = $hostList[0] + '\SQLEXPRESS' }
if (-not $Admins) { $Admins = '' }
$expectedSource = "$Server/$Database"

$backend = @"
# Railway service "backend", project mclabor-production. Built $(Get-Date -Format yyyy-MM-dd) by tools\railway\Build-ProductionVariables.ps1. NEVER COMMIT.
# Seal in the dashboard after import: SITE_PASSWORD_HASH, JWT_SECRET, SYNC_API_KEY.
DATA_SOURCE=production
PRODUCTION_DATABASE_URL=`${{Postgres.DATABASE_URL}}
WEB_AUTH_DATABASE_URL=`${{Postgres.DATABASE_URL}}
DB_SHAPE=production
WEB_WORKERS=2
SITE_MODE=search-only
OFFICE_HOSTS=$hosts
SYNC_API_KEY=$($s.sync)
SYNC_STALE_HOURS=14
SYNC_SOURCE_LABEL=the office McLabor system
SYNC_EXPECTED_SOURCE=$expectedSource
ACCESS_MODE=passcode
SITE_PASSWORD_HASH=$($s.site_hash)
SITE_PASSWORD_LABEL=$($s.label)
SITE_DEFAULT_USER=$DefaultUser
SITE_SESSION_MINUTES=480
SITE_LOCK_FAILURES=5
SITE_LOCK_MINUTES=15
SITE_GLOBAL_LOCK_FAILURES=50
SITE_DEVICE_APPROVAL=false
WEB_ADMINS=$Admins
WEB_USERS=
ACCESS_SEAT_LIMIT=20
JWT_SECRET=$($s.jwt)
ANTHROPIC_API_KEY=
CLAUDE_REAL_DATA_APPROVAL=
LOG_FORMAT=json
ACCESS_LOG=true
LOG_LEVEL=INFO
CORS_ORIGINS=$SiteUrl
"@
$frontend = @"
# Railway service "frontend", project mclabor-production (root directory: frontend).
NEXT_PUBLIC_API_URL=
BACKEND_INTERNAL_URL=http://backend.railway.internal:8000
PORT=3000
HOSTNAME=::
"@
$sync = @"
# tools\sync\sync.env for the office PC that runs the agent against the LIVE server (production). Built $(Get-Date -Format yyyy-MM-dd). NEVER COMMIT.
# Secrets (SQL password of mclabor_web_read, SYNC_API_KEY) are stored with tools\sync\store-sync-secrets.ps1 -Environment production.
DATA_SOURCE=production
OFFICE_HOSTS=$hosts
PRODUCTION_DB_SERVER=$Server
PRODUCTION_DB_NAME=$Database
PRODUCTION_DB_EXPECTED_SERVER_NAME=$Server
PRODUCTION_DB_USER=mclabor_web_read
PRODUCTION_DB_ENCRYPT=true
PRODUCTION_DB_TRUST_SERVER_CERTIFICATE=false
PRODUCTION_WRITES_ENABLED=false
PRODUCTION_WRITE_APPROVAL=
SYNC_API=$SiteUrl
CF_ACCESS_CLIENT_ID=
"@

$out = @{
    'backend.production.variables.env'  = $backend
    'frontend.production.variables.env' = $frontend
    'sync.env'                          = $sync
}
foreach ($name in $out.Keys) {
    $path = Join-Path $dir $name
    [IO.File]::WriteAllText($path, $out[$name].Replace("`r`n", "`n"), (New-Object Text.UTF8Encoding $false))
    icacls $path /inheritance:r | Out-Null
    icacls $path /grant:r "${env:USERDOMAIN}\${env:USERNAME}:(R,W)" | Out-Null
    "written: $path"
}

# verify with the backend's own rules; the production password is decrypted for this check only (never printed)
$sec = Get-Content $dpapiFile | ConvertTo-SecureString
$b = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
try { $env:SITE_PW_CHECK = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($b) } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($b) }
try {
    & (Join-Path $repo 'backend\.venv\Scripts\python.exe') (Join-Path $PSScriptRoot 'verify_production_variables.py') (Join-Path $dir 'backend.production.variables.env') (Join-Path $dir 'sync.env')
    $code = $LASTEXITCODE
} finally { Remove-Item Env:SITE_PW_CHECK -ErrorAction SilentlyContinue }
exit $code
