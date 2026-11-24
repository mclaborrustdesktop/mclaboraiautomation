# Registers (or updates) the Windows scheduled task that runs the synchronization, by default twice a day.
#   powershell -ExecutionPolicy Bypass -File tools\sync\register-sync-task.ps1                       (06:00 and 12:30)
#   powershell -ExecutionPolicy Bypass -File tools\sync\register-sync-task.ps1 -Times "05:30,11:30,17:30"
#   powershell -ExecutionPolicy Bypass -File tools\sync\register-sync-task.ps1 -Remove
# Runs as the CURRENT Windows account (whose DPAPI files hold the secrets), whether or not that account is logged on,
# with a 2-hour limit, no overlap (a run still going is left alone), and a retry 15 minutes after a failure.
param([string]$Times = '06:00,12:30', [string]$TaskName = 'MC Labor one-way sync', [switch]$Remove, [string]$EnvFile = '')
$ErrorActionPreference = 'Stop'
if ($Remove) { Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue; Write-Output "Task '$TaskName' removed."; exit 0 }
$root = Resolve-Path (Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) '..\..')
$script = Join-Path $root 'tools\sync\run-sync.ps1'
$arg = "-NoProfile -ExecutionPolicy Bypass -File `"$script`"" + $(if ($EnvFile) { " -EnvFile `"$EnvFile`"" } else { '' })
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arg -WorkingDirectory (Split-Path $script)
$triggers = @()
foreach ($t in $Times.Split(',')) {
    $t = $t.Trim()
    if ($t -notmatch '^\d{1,2}:\d{2}$') { throw "Bad time '$t' (use HH:MM)." }
    $triggers += New-ScheduledTaskTrigger -Daily -At $t
}
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 2) -MultipleInstances IgnoreNew -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 15) -StartWhenAvailable -RunOnlyIfNetworkAvailable
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType S4U -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $triggers -Settings $settings -Principal $principal -Force | Out-Null
Write-Output "Task '$TaskName' registered for $Times daily as $env:USERDOMAIN\$env:USERNAME (runs even when not logged on; secrets from DPAPI)."
Write-Output "Test it now:  Start-ScheduledTask -TaskName '$TaskName';  then check %LOCALAPPDATA%\MCLabor\sync\logs"
