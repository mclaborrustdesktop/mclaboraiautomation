# READ-ONLY. Run this ON THE LIVE SERVER ITSELF (Remote Desktop session), as a Windows account that is a SQL Server
# administrator. It connects to the local instance over shared memory with Windows authentication - no password is typed
# into anything, no network TLS question arises, and the server's identity is certain because you are on it.
#
#   Right-click > Run with PowerShell, or:  powershell -ExecutionPolicy Bypass -File .\Run-LiveBackupChecks-OnServer.ps1
#
# What it does: 1) runs 0-live-backup-status.sql (from the same folder; refused if its text differs from the reviewed
# version) - nine grids about the backups of McLabor; 2) RESTORE VERIFYONLY of the newest full backup file (reads the file,
# restores nothing); 3) writes live-backup-report-<date>.md next to this script and copies it to the clipboard so it
# can be pasted to the owner. Nothing is created, changed, backed up, restored or deleted. No business row is read.
param([string]$Instance = '.\SQLEXPRESS')
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$sqlFile = Join-Path $here '0-live-backup-status.sql'
$pinned = '4e940fe9e7e0e280131ef9dc24f7c1a1ab5821fe8bd7c450ebda8adfa2cfaf9b'   # SHA-256 of the reviewed script (LF line endings)
if (-not (Test-Path $sqlFile)) { throw "0-live-backup-status.sql must be in the same folder as this script." }
$text = [IO.File]::ReadAllText($sqlFile, [Text.Encoding]::UTF8).TrimStart([char]0xFEFF).Replace("`r`n", "`n")
$sha = [BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($text))).Replace('-', '').ToLower()
if ($sha -ne $pinned) { throw "0-live-backup-status.sql differs from the reviewed version (hash $sha). Nothing was run." }

$cn = New-Object System.Data.SqlClient.SqlConnection "Server=$Instance;Database=master;Integrated Security=true;Application Name=mclabor-backup-gate-onserver"
$messages = New-Object System.Collections.Generic.List[string]
$cn.add_InfoMessage({ param($s, $e) $messages.Add($e.Message) })
$cn.FireInfoMessageEventOnUserErrors = $false
$cn.Open()

function Query($sql, $timeout = 60) {
    $cmd = $cn.CreateCommand(); $cmd.CommandText = $sql; $cmd.CommandTimeout = $timeout
    $da = New-Object System.Data.SqlClient.SqlDataAdapter $cmd
    $ds = New-Object System.Data.DataSet
    [void]$da.Fill($ds)
    return $ds.Tables
}
function MdTable($table, $limit = 20) {
    $cols = @($table.Columns | ForEach-Object { $_.ColumnName })
    $out = @(); $out += ('| ' + ($cols -join ' | ') + ' |'); $out += ('|' + ('---|' * $cols.Count))
    $rows = @($table.Rows)
    foreach ($r in $rows | Select-Object -First $limit) { $out += '| ' + (($cols | ForEach-Object { ("$($r[$_])" -replace '\|', '/').Substring(0, [Math]::Min(60, "$($r[$_])".Length)) }) -join ' | ') + ' |' }
    if ($rows.Count -gt $limit) { $out += "| ... $($rows.Count - $limit) more row(s) |" + (' |' * ($cols.Count - 1)) }
    if ($rows.Count -eq 0) { $out += '| (no rows) |' + (' |' * ($cols.Count - 1)) }
    return ($out -join "`n")
}

# identity and permissions (fixed queries)
$id = (Query "SELECT CAST(SERVERPROPERTY('ServerName') AS nvarchar(128)) AS server_name, CAST(SERVERPROPERTY('MachineName') AS nvarchar(128)) AS machine, SUSER_SNAME() AS login, IS_SRVROLEMEMBER('sysadmin') AS sysadmin, HAS_PERMS_BY_NAME('msdb.dbo.backupset','OBJECT','SELECT') AS read_backup_history, HAS_PERMS_BY_NAME(NULL,NULL,'VIEW SERVER STATE') AS view_server_state")[0].Rows[0]
Write-Output "connected to $($id.server_name) on machine $($id.machine) as $($id.login) (sysadmin=$($id.sysadmin))"
if ($id.machine -ne $env:COMPUTERNAME) { throw "This script must run ON the server: the instance is on $($id.machine) but this computer is $env:COMPUTERNAME. Nothing was run." }
if ($id.read_backup_history -ne 1 -or $id.view_server_state -ne 1) { throw "This Windows account may not read the backup history / server state. Sign in as a SQL Server administrator. Nothing was run." }

# the reviewed script, its own server guard satisfied with the verified name
$sql = $text.Replace("N'LIVE-HOST\SQLEXPRESS'", "N'$($id.server_name)'")
$grids = @()
foreach ($batch in ($sql -split "(?m)^\s*GO\s*$")) {
    if (-not $batch.Trim()) { continue }
    $grids += @(Query $batch 120)
}

$stamp = Get-Date -Format 'yyyy-MM-dd_HHmmss'
$report = @("# Live server backup checks ($stamp)", "", "Server: ``$($id.server_name)`` (machine $($id.machine)). Run as: ``$($id.login)``. Script: 0-live-backup-status.sql (hash verified). Read-only.", "")
$summary = @()
$latest = $grids[2]
$full = @($latest.Rows | Where-Object { "$($_.type_name)" -eq 'FULL' }) | Select-Object -First 1
$verdict = if ($grids.Count -gt 7 -and $grids[7].Rows.Count) { "$($grids[7].Rows[0][0])" } else { '(no verdict)' }
if ($null -eq $full) {
    $summary += 'GATE FAILED: no full backup of McLabor is recorded on this server.'
} else {
    $ok = ([int]$full.age_hours -le 24) -and ([bool]$full.has_backup_checksums) -and (-not [bool]$full.is_damaged) -and ([int]$full.file_exists -eq 1)
    $summary += ("{0}: newest full backup finished {1}, {2} h ago, {3} MB, checksums={4}, damaged={5}, copy_only={6}, by {7}" -f $(if ($ok) { 'GATE PASSED (pending VERIFYONLY below)' } else { 'GATE FAILED' }), $full.backup_finish_date, $full.age_hours, $full.size_mb, $full.has_backup_checksums, $full.is_damaged, $full.is_copy_only, $full.taken_by)
    $summary += "file: $($full.backup_file) (exists=$($full.file_exists))"
}
$summary += "restores recorded on this server: $($grids[4].Rows.Count)"
$summary += "server verdict: $verdict"
if ($grids.Count -gt 8) { $summary += 'free space: ' + (($grids[8].Rows | ForEach-Object { "$($_.drive): $($_.free_mb) MB" }) -join '; ') }

# RESTORE VERIFYONLY of the newest full backup (reads the file; restores nothing)
if ($null -ne $full -and [int]$full.file_exists -eq 1) {
    $file = "$($full.backup_file)".Replace("'", "''")
    $with = if ([bool]$full.has_backup_checksums) { ' WITH CHECKSUM' } else { '' }
    Write-Output "RESTORE VERIFYONLY of $($full.backup_file) (a few minutes; reads the file only) ..."
    $messages.Clear()
    try {
        $cmd = $cn.CreateCommand(); $cmd.CommandText = "RESTORE VERIFYONLY FROM DISK = N'$file'$with"; $cmd.CommandTimeout = 3600
        [void]$cmd.ExecuteNonQuery()
        $summary += 'VERIFYONLY: ' + $(if ($messages.Count) { $messages -join ' / ' } else { 'completed without error' })
    } catch {
        $summary += 'VERIFYONLY FAILED: ' + $_.Exception.Message
    }
} else {
    $summary += 'VERIFYONLY skipped: no present full backup file.'
}
$cn.Close()

$report += '## Summary', ''
$report += ($summary | ForEach-Object { "- $_" })
$report += ''
for ($i = 0; $i -lt $grids.Count; $i++) { $report += "## Grid $($i + 1)", '', (MdTable $grids[$i]), '' }
$path = Join-Path $here "live-backup-report-$stamp.md"
[IO.File]::WriteAllText($path, ($report -join "`n"), (New-Object Text.UTF8Encoding $false))
try { Set-Clipboard -Value ($report -join "`n"); $clip = ' and copied to the clipboard' } catch { $clip = '' }
Write-Output ''
$summary | ForEach-Object { Write-Output "  $_" }
Write-Output ''
Write-Output "Report written to $path$clip. Nothing on this server was changed."
