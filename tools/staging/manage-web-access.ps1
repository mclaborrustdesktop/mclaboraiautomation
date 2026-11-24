# Gives a staff member access to the website with real data, or takes it away. Edits the WEB_ADMINS / WEB_USERS
# lines of a settings file; nothing in the McLabor database changes.
#   powershell -ExecutionPolicy Bypass -File tools\staging\manage-web-access.ps1 -Initials XX -Role user
#   powershell -ExecutionPolicy Bypass -File tools\staging\manage-web-access.ps1 -Initials XX -Role admin -SetPassword
#   powershell -ExecutionPolicy Bypass -File tools\staging\manage-web-access.ps1 -Initials XX -Role none
#   powershell -ExecutionPolicy Bypass -File tools\staging\manage-web-access.ps1 -List
#   admin = everything (user management, system status); user = look-up only; none = removed from both lists.
# -EnvFile: the settings file to edit. Default backend\.env (the active website). While the website is in DEMO that
#   file does not exist; use -EnvFile backend\.env.off to prepare the staging settings for later.
# -SetPassword: also sets the person's web password (asks twice, hidden; 12+ characters). Only in "login" mode;
#   with a gateway the gateway signs people in and no web password exists.
# Restart the website's backend afterwards: the lists are read at start-up.
param(
    [string]$Initials = '',
    [ValidateSet('admin', 'user', 'none', '')][string]$Role = '',
    [string]$EnvFile = '',
    [switch]$SetPassword,
    [switch]$List
)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Resolve-Path (Join-Path $here '..\..')
if (-not $EnvFile) { $EnvFile = Join-Path $root 'backend\.env' }
if (-not (Test-Path $EnvFile)) { throw "Settings file not found: $EnvFile. The website is in DEMO (no backend\.env); use -EnvFile backend\.env.off to prepare the staging settings." }
$lines = @(Get-Content $EnvFile)

function Get-Names([string]$key) {
    $v = ($lines | Where-Object { $_ -match "^$key=" } | Select-Object -First 1) -replace "^$key=", ''
    return @($v -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
}
function Set-Names([string]$key, [string[]]$names) {
    $script:lines = @($script:lines | Where-Object { $_ -notmatch "^$key=" }) + "$key=$($names -join ',')"
}

$admins = Get-Names 'WEB_ADMINS'
$users = Get-Names 'WEB_USERS'
if ($List -or -not $Initials) {
    Write-Output "Settings file: $EnvFile"
    Write-Output "  WEB_ADMINS (everything): $(if ($admins) { $admins -join ', ' } else { '(nobody)' })"
    Write-Output "  WEB_USERS (look-up only): $(if ($users) { $users -join ', ' } else { '(nobody)' })"
    if (-not $admins -and -not $users) { Write-Warning 'Nobody can use the website with these settings.' }
    exit 0
}
if ($Initials -notmatch '^[A-Za-z0-9@._-]{1,80}$') { throw 'Initials (or OfficeStaffID or e-mail) contain characters that are not allowed.' }
if (-not $Role) { throw 'Give -Role admin, user or none.' }

$admins = @($admins | Where-Object { $_.ToLower() -ne $Initials.ToLower() })
$users = @($users | Where-Object { $_.ToLower() -ne $Initials.ToLower() })
switch ($Role) {
    'admin' { $admins += $Initials }
    'user' { $users += $Initials }
}
Set-Names 'WEB_ADMINS' $admins
Set-Names 'WEB_USERS' $users
[IO.File]::WriteAllLines((Resolve-Path $EnvFile), $lines)
Write-Output "$Initials is now: $Role  (WEB_ADMINS: $(if ($admins) { $admins -join ',' } else { '-' }); WEB_USERS: $(if ($users) { $users -join ',' } else { '-' }))"

if ($SetPassword -and $Role -ne 'none') {
    # The password store belongs to the environment in the settings file; run-readonly.ps1 loads that file into one process.
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $here 'run-readonly.ps1') -EnvFile $EnvFile -m app.webauth set-password $Initials
    if ($LASTEXITCODE -ne 0) { Write-Warning 'The password was not set. The access list was changed anyway.' }
}
Write-Output 'Restart the website backend for the change to take effect.'
