# Creates the separate PRODUCTION project on Railway with the official CLI, in the owner's workspace, from the prepared
# variable files. PREPARED 2026-11-27, NOT EXECUTED: without -Execute it only prints the plan. Every step was used for
# the staging project (docs/cloud/16); the API field names are re-checked at run time and the script stops at the first
# error. Billable: a new project with three services and a 1 GB volume (about 12 USD of usage a month inside the Pro
# allowance, docs/cloud/19 section C3) - needs the owner's explicit approval before -Execute.
#
#   powershell -ExecutionPolicy Bypass -File deploy\railway\create-production.ps1              # plan only
#   powershell -ExecutionPolicy Bypass -File deploy\railway\create-production.ps1 -Execute     # after approval
#
# Afterwards (by hand, dashboard): seal SITE_PASSWORD_HASH, JWT_SECRET and SYNC_API_KEY on the backend service.
param([switch]$Execute, [string]$ProjectName = 'mclabor-production', [string]$Workspace = "mclaborrustdesktop's Projects",
      [string]$Repo = 'mclaborrustdesktop/mclaboraiautomation', [string]$Branch = 'main')
$ErrorActionPreference = 'Stop'
$env:PATH = "$env:USERPROFILE\tools\node;$env:PATH"
$repoDir = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$dir = Join-Path $env:LOCALAPPDATA 'MCLabor\production'
$backendVars = Join-Path $dir 'backend.production.variables.env'
$frontendVars = Join-Path $dir 'frontend.production.variables.env'

function Step($n, $text) { Write-Output ("{0,2}. {1}" -f $n, $text) }
function Run($cmd) {
    Write-Output "    > $cmd"
    if ($Execute) { $out = Invoke-Expression $cmd; if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) { throw "failed ($LASTEXITCODE): $cmd" }; return $out }
}
function VarLines($file) {
    Get-Content $file | Where-Object { $_ -and -not $_.StartsWith('#') -and $_.Contains('=') }
}

Write-Output ("MODE: " + $(if ($Execute) { 'EXECUTE (creates billable resources)' } else { 'PLAN ONLY - nothing is created' }))
Step 0 "Preconditions"
$who = railway whoami 2>&1
if ("$who" -notmatch 'ray@mclabor.com') { throw "Railway CLI is not logged in as ray@mclabor.com: $who" }
Write-Output "    logged in as ray@mclabor.com"
foreach ($f in @($backendVars, $frontendVars)) { if (-not (Test-Path $f)) { throw "Missing $f - run tools\railway\Build-ProductionVariables.ps1 first" } }
Write-Output "    verifying the variable files with the backend's rules:"
& (Join-Path $repoDir 'backend\.venv\Scripts\python.exe') (Join-Path $repoDir 'tools\railway\verify_production_variables.py') $backendVars (Join-Path $dir 'sync.env') | ForEach-Object { "    $_" }
if ($LASTEXITCODE -ne 0) { if ($Execute) { throw "the variable files do not pass verification" } else { Write-Output "    (plan continues; -Execute would stop here until every check passes)" } }
$existing = railway list 2>&1
if ("$existing" -match [regex]::Escape($ProjectName)) { throw "A project named $ProjectName already exists in the workspace - stop, do not create a second one." }

Step 1 "Create the project (default environment 'production' = the REAL production this time) and link this folder to it"
Run "railway init --name $ProjectName --workspace `"$Workspace`" --json"
Run "railway link --project $ProjectName --environment production --workspace `"$Workspace`""

Step 2 "PostgreSQL from the template (private network only; no TCP proxy is ever created)"
Run "railway add --database postgres --json"

Step 3 "Services backend and frontend from the GitHub repository, branch $Branch (empty until step 6)"
Run "railway add --service backend --repo $Repo --branch $Branch --json"
Run "railway add --service frontend --repo $Repo --branch $Branch --json"

Step 4 "Service settings: root directory and config file (config-as-code path) - same values as staging"
$settings = @(
    @{ service = 'backend';  root = '/';         cfg = 'deploy/railway/backend.railway.json' },
    @{ service = 'frontend'; root = 'frontend';  cfg = 'frontend/railway.json' }
)
foreach ($st in $settings) {
    $varFile = Join-Path $env:TEMP "railway-si-$($st.service).json"
    Write-Output "    serviceInstanceUpdate($($st.service)): rootDirectory=$($st.root) railwayConfigFile=$($st.cfg)"
    if ($Execute) {
        $ids = railway status --json | ConvertFrom-Json
        $svc = $ids.services.edges.node | Where-Object { $_.name -eq $st.service }
        @{ s = $svc.id; e = $ids.environments.edges.node[0].id; i = @{ rootDirectory = $st.root; railwayConfigFile = $st.cfg } } | ConvertTo-Json -Compress | Set-Content $varFile -Encoding ascii
        Run "railway api 'mutation(`$s:String!,`$e:String!,`$i:ServiceInstanceUpdateInput!){ serviceInstanceUpdate(serviceId:`$s, environmentId:`$e, input:`$i) }' --variables @$varFile"
        Remove-Item $varFile
    }
}

Step 5 "Variables (from the prepared files; --skip-deploys so nothing builds before everything is set)"
foreach ($line in VarLines $backendVars) { $k = $line.Split('=')[0]; Write-Output "    backend  $k"; if ($Execute) { railway variable set --service backend --skip-deploys "$line" | Out-Null } }
foreach ($line in VarLines $frontendVars) { $k = $line.Split('=')[0]; Write-Output "    frontend $k"; if ($Execute) { railway variable set --service frontend --skip-deploys "$line" | Out-Null } }

Step 6 "Public address for the frontend ONLY, then CORS_ORIGINS on the backend"
$domain = Run "railway domain --service frontend --json"
if ($Execute) { $siteHost = ($domain | ConvertFrom-Json).domain; Run "railway variable set --service backend --skip-deploys CORS_ORIGINS=https://$siteHost"; Write-Output "    production website: https://$siteHost" }

Step 7 "First deployments from the source"
Run "railway redeploy --service backend --from-source -y"
Run "railway redeploy --service frontend --from-source -y"

Step 8 "Backups: daily + weekly volume snapshots, point-in-time recovery, one on-demand snapshot"
Run "railway postgres pitr schedule set --daily --weekly --service Postgres"
Run "railway postgres pitr enable --service Postgres"
Run "railway postgres pitr backup create --service Postgres"

Step 9 "Checks (run by hand after step 7 finishes)"
Write-Output "    railway domain list --service backend     -> must be empty (no public address)"
Write-Output "    railway domain list --service Postgres    -> must be empty; railway variable --service Postgres must show no *TCP_PROXY* / DATABASE_PUBLIC_URL"
Write-Output "    https://<host>/api/health                 -> environment production, access_mode passcode, writes false, site_mode search-only"
Write-Output "    staging_checks_passcode.py <https://host> -> all passed with the PRODUCTION password (never the staging one)"
Write-Output "    dashboard: seal SITE_PASSWORD_HASH, JWT_SECRET, SYNC_API_KEY; Postgres > Backups shows the schedule and the snapshot"
Write-Output "    restore drill: railway postgres pitr backup restore (into a scratch service), then delete the scratch service"
Write-Output ""
Write-Output "Estimated usage: about 12 USD a month (backend + frontend + PostgreSQL 1 GB volume, snapshots, PITR storage), inside the 20 USD included in Pro."
