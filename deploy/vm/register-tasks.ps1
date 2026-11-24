# Run ON THE VM as administrator. Registers the scheduled tasks: nightly backup at 02:00, a monthly backup on the
# 1st at 03:00, the restore test on the 2nd at 03:30, and a 5-minute health check that writes an Error event when
# the website stops answering (the monitoring alert reads it). Tasks run as SYSTEM (sqlcmd uses Windows sign-in).
#Requires -RunAsAdministrator
param([string]$Root = 'C:\mclabor', [string]$Database = 'McLabor')
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$ps = "powershell.exe"
function Register([string]$name, [string]$args_, $trigger) {
    $action = New-ScheduledTaskAction -Execute $ps -Argument "-NoProfile -ExecutionPolicy Bypass $args_"
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 3) -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings -User 'SYSTEM' -RunLevel Highest -Force | Out-Null
    Write-Output "registered $name"
}
Register 'MC Labor - nightly SQL backup'  "-File `"$here\backup-sql.ps1`" -Database $Database -Root $Root" (New-ScheduledTaskTrigger -Daily -At 02:00)
Register 'MC Labor - monthly SQL backup'  "-File `"$here\backup-sql.ps1`" -Database $Database -Root $Root -Monthly" (New-ScheduledTaskTrigger -Monthly -DaysOfMonth 1 -At 03:00)
Register 'MC Labor - monthly restore test' "-File `"$here\restore-test.ps1`" -Database $Database -Root $Root" (New-ScheduledTaskTrigger -Monthly -DaysOfMonth 2 -At 03:30)
$health = "-Command `"try { `$r = Invoke-RestMethod -Uri http://127.0.0.1:8000/api/ready -TimeoutSec 15; if (`$r.status -ne 'ready') { throw `$r.checks } } catch { if (-not [Diagnostics.EventLog]::SourceExists('MCLaborWeb')) { New-EventLog -LogName Application -Source MCLaborWeb }; Write-EventLog -LogName Application -Source MCLaborWeb -EntryType Error -EventId 2001 -Message ('website not ready: ' + `$_) }`""
Register 'MC Labor - website health check' $health (New-ScheduledTaskTrigger -Once -At (Get-Date).Date -RepetitionInterval (New-TimeSpan -Minutes 5))
