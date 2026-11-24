# Lets ONE staff member sign in to the STAGING website as a website administrator.
#   powershell -ExecutionPolicy Bypass -File tools\staging\add-pilot-user.ps1 XX        (XX = their initials in the staff list)
# Run it in your own PowerShell window: it asks you to type a new web password twice (typing is hidden, 12+ characters).
# The password is stored (hashed) in backend\web_auth_staging.db. Nothing is written to the McLabor database,
# and the Access password is not read or changed. Restart the website's backend afterwards.
param([Parameter(Mandatory = $true)][string]$Initials)
$ErrorActionPreference = 'Stop'
if ($Initials -notmatch '^[A-Za-z0-9]{1,10}$') { throw "Initials should be letters or digits only." }
$here    = Split-Path -Parent $MyInvocation.MyCommand.Path
$envFile = Join-Path $here '..\..\backend\.env'
if (-not (Test-Path $envFile)) { throw "backend\.env not found: the website is in DEMO." }

& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $here 'run-in-staging.ps1') -m app.webauth set-password $Initials
if ($LASTEXITCODE -ne 0) { throw "The password was not set, so nothing else was changed." }

$lines = @(Get-Content $envFile)
$current = ($lines | Where-Object { $_ -match '^WEB_ADMINS=' }) -replace '^WEB_ADMINS=', ''
$names = @($current -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
if ($names -notcontains $Initials) { $names += $Initials }
$lines = @($lines | Where-Object { $_ -notmatch '^WEB_ADMINS=' }) + "WEB_ADMINS=$($names -join ',')"
[IO.File]::WriteAllLines((Resolve-Path $envFile), $lines)
Write-Output "Done. $Initials can sign in at http://localhost:3000 after the backend is restarted."
