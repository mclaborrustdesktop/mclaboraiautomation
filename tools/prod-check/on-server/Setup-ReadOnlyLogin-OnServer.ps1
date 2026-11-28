# ONE-TIME SETUP, RUN ON THE LIVE SERVER ITSELF (LIVE-HOST) BY THE CLIENT'S OWN ADMINISTRATOR.
# Start it with RUN-ME.cmd in this folder (right-click > Run as administrator; administrator rights are needed only
# for the certificate step - without them the script does everything else and says so).
#
# Nothing leaves this computer except the "results" folder, which holds no password in clear and no business data.
# No password is typed into anything of this project: the script uses the Windows account it runs as (if that account
# is not a SQL Server administrator it asks for a SQL administrator login, typed here, kept in memory only).
#
# What it does, in order, asking before anything that changes the server:
#   1. Checks it is on LIVE-HOST, instance SQLEXPRESS, database McLabor present. Otherwise it stops; nothing changed.
#   2. Backup check (read-only): the reviewed 0-live-backup-status.sql, then RESTORE VERIFYONLY of the newest full backup.
#   3. If no verified full backup exists (asks; required) or it is older than a day (asks; recommended): a COPY_ONLY full
#      backup with checksum (4-live-copyonly-backup-with-checksum.sql). Reads the database only; disconnects nobody.
#   4. Creates the login mclabor_web_read with a 32-character generated password (proposed-grants-production.sql):
#      SELECT on 288 approved columns of 33 tables, DENY on every write right and on the 17 sensitive columns.
#      If the login exists already (a re-run), only its password is set to the new one.
#   5. Verifies it (verify-readonly-login.sql, 11 checks, impersonation) and tests it live as that login: one allowed
#      read, a sensitive column refused, UPDATE / INSERT / DELETE refused (all on zero rows: even if a refusal failed,
#      nothing could change). Note: like every login, it can still read SQL Server's own catalog views and the backup
#      history in msdb (public defaults); those hold no business data.
#   6. Certificate (asks; administrator window; SQL Server restarts for about a minute, Access users reconnect):
#      certificate-setup.ps1 installs a server certificate so the office PC can verify this server; its PUBLIC part is
#      exported to results\. Skipped with a note if the window is not elevated; can be run later.
#   7. Encrypts the new password to the office PC's transfer key (transfer-key.cer, a public key: only the office PC
#      holds the private half) -> results\mclabor_web_read.password.cms. If that fails, the password is shown ONCE here.
#   Writes results\setup-report-<date>.md (no password, no data) and copies it to the clipboard.
#
# Every SQL file is refused if its text differs from the reviewed version (SHA-256). Nothing restores, drops or replaces
# a database; no business row is read; no existing login, permission, record or setting is changed. Undo (as administrator,
# Management Studio): USE [McLabor]; DROP USER [mclabor_web_read]; DROP ROLE [mclabor_web_readonly]; USE [master]; DROP LOGIN [mclabor_web_read];
param([string]$Instance = '.\SQLEXPRESS', [switch]$SkipCertificate)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$results = Join-Path $here 'results'
New-Item -ItemType Directory -Force $results | Out-Null
$expectedComputer = 'LIVE-HOST'
$expectedServer = "$expectedComputer\SQLEXPRESS"
$stamp = Get-Date -Format 'yyyy-MM-dd_HHmmss'
# the server guard inside the reviewed SQL files (kept as two pieces so that filling in the office names leaves it alone)
$guard = "N'LIVE-" + "HOST\SQLEXPRESS'"
$pins = @{
    '0-live-backup-status.sql'                 = '4e940fe9e7e0e280131ef9dc24f7c1a1ab5821fe8bd7c450ebda8adfa2cfaf9b'
    '4-live-copyonly-backup-with-checksum.sql' = 'a12342e141584eaf6c72db8651a8582e3a8f1b2e2f7b2f6039a620c692261d89'
    'proposed-grants-production.sql'           = '079ec2522372a0c1cfbc1c0c300cc3ed481d2b0d0b4e996221174e6b8d5c9ce4'
    'verify-readonly-login.sql'                = '6b5376d8c086e7f065a2a1e66486431a2d5f1304213f1d6c9e72f7676595af47'
}
$report = New-Object System.Collections.Generic.List[string]
$summary = New-Object System.Collections.Generic.List[string]
function Say($t) { Write-Output $t; $summary.Add($t) }
function Ask($question) { $a = Read-Host "$question  [Y/N]"; return ($a.Trim().ToUpper() -eq 'Y') }
function ReviewedSql($name) {
    $p = Join-Path $here $name
    if (-not (Test-Path $p)) { throw "$name must be in the same folder as this script." }
    $t = [IO.File]::ReadAllText($p, [Text.Encoding]::UTF8).TrimStart([char]0xFEFF).Replace("`r`n", "`n")
    $sha = [BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($t))).Replace('-', '').ToLower()
    if ($sha -ne $pins[$name]) { throw "$name differs from the reviewed version (hash $sha). Nothing was run." }
    return $t
}
function Batches($sql) { return @($sql -split "(?m)^\s*GO\s*$" | Where-Object { $_.Trim() }) }
function MdTable($table, $limit = 20) {
    $cols = @($table.Columns | ForEach-Object { $_.ColumnName })
    $out = @(); $out += ('| ' + ($cols -join ' | ') + ' |'); $out += ('|' + ('---|' * $cols.Count))
    $rows = @($table.Rows)
    foreach ($r in $rows | Select-Object -First $limit) { $out += '| ' + (($cols | ForEach-Object { $v = "$($r[$_])" -replace '\|', '/'; $v.Substring(0, [Math]::Min(60, $v.Length)) }) -join ' | ') + ' |' }
    if ($rows.Count -gt $limit) { $out += "| ... $($rows.Count - $limit) more row(s) |" + (' |' * ($cols.Count - 1)) }
    if ($rows.Count -eq 0) { $out += '| (no rows) |' + (' |' * ($cols.Count - 1)) }
    return ($out -join "`n")
}

# ---- connection: the Windows account of this window; a SQL administrator login only if that account is not one
$messages = New-Object System.Collections.Generic.List[string]
$sqlLogin = ''; $sqlSecure = $null
function Open-Admin($database) {
    $cs = "Server=$Instance;Database=$database;Application Name=mclabor-onetime-setup;Connect Timeout=15;"
    if ($script:sqlLogin) { $cs += "User ID=$($script:sqlLogin);Password=$((New-Object System.Net.NetworkCredential('', $script:sqlSecure)).Password);" } else { $cs += 'Integrated Security=true;' }
    $c = New-Object System.Data.SqlClient.SqlConnection $cs
    $c.add_InfoMessage({ param($s, $e) $script:messages.Add($e.Message) })
    $c.FireInfoMessageEventOnUserErrors = $false
    $c.Open()
    return $c
}
function Query($c, $sql, $timeout = 120) {
    $cmd = $c.CreateCommand(); $cmd.CommandText = $sql; $cmd.CommandTimeout = $timeout
    $da = New-Object System.Data.SqlClient.SqlDataAdapter $cmd
    $ds = New-Object System.Data.DataSet
    [void]$da.Fill($ds)
    return @($ds.Tables)
}
$identitySql = "SELECT CAST(SERVERPROPERTY('ServerName') AS nvarchar(128)) AS server_name, CAST(SERVERPROPERTY('MachineName') AS nvarchar(128)) AS machine, CAST(SERVERPROPERTY('ProductVersion') AS nvarchar(32)) AS version, SUSER_SNAME() AS login, IS_SRVROLEMEMBER('sysadmin') AS sysadmin, ISNULL(CAST(DB_ID('McLabor') AS nvarchar(10)), '') AS mclabor_db"

Write-Output "MC Labor one-time setup on $env:COMPUTERNAME ($stamp)"
if ($env:COMPUTERNAME -ne $expectedComputer) { throw "This package is for $expectedComputer, but this computer is $env:COMPUTERNAME. Nothing was done." }
$cn = $null
try { $cn = Open-Admin 'master' } catch { Write-Output "Windows account $env:USERDOMAIN\$env:USERNAME cannot sign in to SQL Server ($($_.Exception.Message))." }
if ($cn) { $id = (Query $cn $identitySql)[0].Rows[0]; if ([int]$id.sysadmin -ne 1) { Write-Output "Windows account $($id.login) is not a SQL Server administrator."; $cn.Close(); $cn = $null } }
if (-not $cn) {
    Write-Output 'A SQL Server administrator login is needed (for example sa). It is used in this window only and not stored.'
    $sqlLogin = (Read-Host 'SQL Server administrator login name').Trim()
    $sqlSecure = Read-Host -AsSecureString "Password of $sqlLogin (hidden)"
    $cn = Open-Admin 'master'
    $id = (Query $cn $identitySql)[0].Rows[0]
    if ([int]$id.sysadmin -ne 1) { throw "$($id.login) is not a SQL Server administrator either. Nothing was done." }
}
if ("$($id.machine)" -ne $env:COMPUTERNAME) { throw "The instance answers from machine $($id.machine), not this computer. Nothing was done." }
if ("$($id.server_name)" -ne $expectedServer) { throw "The instance calls itself '$($id.server_name)', expected '$expectedServer'. Nothing was done." }
if ("$($id.mclabor_db)" -eq '') { throw 'Database McLabor was not found on this instance. Nothing was done.' }
Say "Server $($id.server_name) (SQL Server $($id.version)), signed in as $($id.login), administrator: yes, database McLabor: present."
$report.Add("# MC Labor one-time server setup ($stamp)"); $report.Add('')
$report.Add("Server ``$($id.server_name)`` on ``$($id.machine)``, SQL Server $($id.version). Run as ``$($id.login)``. Package scripts verified by hash."); $report.Add('')

# ---- 2. backup check (read-only)
Write-Output ''; Write-Output '--- 2. Backup check (read-only) ---'
$statusSql = (ReviewedSql '0-live-backup-status.sql').Replace($guard, "N'$($id.server_name)'")
$grids = @(); foreach ($b in (Batches $statusSql)) { $grids += @(Query $cn $b 120) }
$full = $null
if ($grids.Count -gt 2) { $full = @($grids[2].Rows | Where-Object { "$($_.type_name)" -eq 'FULL' }) | Select-Object -First 1 }
$verified = $false; $fresh = $false
if ($null -eq $full) {
    Say 'Backup check: NO full backup of McLabor is recorded on this server.'
} else {
    Say ("Backup check: newest full backup finished {0} ({1} h ago), {2} MB, checksums={3}, damaged={4}, by {5}, file present={6}" -f $full.backup_finish_date, $full.age_hours, $full.size_mb, $full.has_backup_checksums, $full.is_damaged, $full.taken_by, $full.file_exists)
    if ([int]$full.file_exists -eq 1 -and -not [bool]$full.is_damaged) {
        $file = "$($full.backup_file)".Replace("'", "''")
        $with = if ([bool]$full.has_backup_checksums) { ' WITH CHECKSUM' } else { '' }
        Write-Output "RESTORE VERIFYONLY of $($full.backup_file) (reads the file only; a few minutes) ..."
        $messages.Clear()
        try {
            $cmd = $cn.CreateCommand(); $cmd.CommandText = "RESTORE VERIFYONLY FROM DISK = N'$file'$with"; $cmd.CommandTimeout = 3600
            [void]$cmd.ExecuteNonQuery()
            $verified = $true
            Say ('VERIFYONLY: ' + $(if ($messages.Count) { $messages -join ' / ' } else { 'completed without error' }))
        } catch { Say ('VERIFYONLY FAILED: ' + $_.Exception.Message) }
        $fresh = $verified -and ([int]$full.age_hours -le 24)
    } else { Say 'The newest full backup file is missing or marked damaged; it cannot be verified.' }
}
for ($i = 0; $i -lt $grids.Count; $i++) { $report.Add("## Backup check, grid $($i + 1)"); $report.Add(''); $report.Add((MdTable $grids[$i])); $report.Add('') }

# ---- 3. copy-only backup when needed
Write-Output ''; Write-Output '--- 3. Safety backup ---'
$takeBackup = $false
if (-not $verified) {
    Write-Output 'No verified full backup exists. A fresh COPY_ONLY full backup with checksum is REQUIRED before the login is created.'
    Write-Output 'It reads the database (about 1.7 GB, a few minutes), disconnects nobody and changes no backup routine.'
    if (-not (Ask 'Take the safety backup now?')) { Say 'Stopped by the administrator at the backup step. No login was created, nothing was changed.'; $cn.Close(); exit 3 }
    $takeBackup = $true
} elseif (-not $fresh) {
    Write-Output 'The newest verified full backup is older than one day. A fresh COPY_ONLY full backup is recommended (not required for creating a login).'
    $takeBackup = Ask 'Take a fresh safety backup now (a few minutes, nobody disconnected)?'
} else { Say 'Safety backup: a verified full backup younger than one day exists; no new backup needed.' }
if ($takeBackup) {
    $backupSql = (ReviewedSql '4-live-copyonly-backup-with-checksum.sql').Replace($guard, "N'$($id.server_name)'")
    $messages.Clear()
    foreach ($b in (Batches $backupSql)) { $bg = @(Query $cn $b 7200); if ($bg.Count) { $report.Add('## Safety backup, header'); $report.Add(''); $report.Add((MdTable $bg[-1] 3)); $report.Add('') } }
    Say ('Safety backup: ' + (($messages | Where-Object { $_ -match 'Backing up to|Backup file|processed|successfully|valid' }) -join ' / '))
}

# ---- 4. the read-only login
Write-Output ''; Write-Output '--- 4. Read-only login mclabor_web_read ---'
Write-Output 'Creates one login that can only READ the approved columns (288 columns, 33 tables) and is explicitly refused every'
Write-Output 'write right and the 17 sensitive columns (SSN, bank, date of birth, I-9/W-4, citizenship, race, sex, staff passwords).'
if (-not (Ask 'Create the read-only login now?')) { Say 'Stopped by the administrator before the login step. Nothing was changed.'; $cn.Close(); exit 3 }
$rng = [Security.Cryptography.RandomNumberGenerator]::Create()
do { $bytes = New-Object byte[] 24; $rng.GetBytes($bytes); $password = [Convert]::ToBase64String($bytes).TrimEnd('=') } until ($password -cmatch '[A-Z]' -and $password -cmatch '[a-z]' -and $password -match '[0-9]')
$existed = [int](Query $cn "SELECT COUNT(*) FROM sys.server_principals WHERE name = N'mclabor_web_read'")[0].Rows[0][0] -gt 0
$grantsSql = (ReviewedSql 'proposed-grants-production.sql').Replace($guard, "N'$($id.server_name)'").Replace('<<TYPE-A-LONG-PASSWORD-HERE>>', $password)
$messages.Clear(); $final = @()
foreach ($b in (Batches $grantsSql)) { $g = @(Query $cn $b 300); if ($g.Count) { $final = $g } }
$grantsSql = $null
if ($existed) {
    $cmd = $cn.CreateCommand(); $cmd.CommandText = "ALTER LOGIN [mclabor_web_read] WITH PASSWORD = N'$password'"; [void]$cmd.ExecuteNonQuery()
    Say 'Login mclabor_web_read existed already (earlier run): its password was set to the new one; permissions re-applied (the script is idempotent).'
} else { Say 'Login mclabor_web_read created.' }
$n = $final[0].Rows[0]; $d = $final[1].Rows[0]; $u = $final[2].Rows.Count
$okGrants = ([int]$n[0] -eq 288 -and [int]$n[1] -eq 33 -and [int]$d[0] -eq 18 -and [int]$d[1] -eq 17 -and $u -eq 0)
Say ("Permissions: {0} readable columns on {1} tables (expect 288/33), {2} database refusals (expect 18), {3} sensitive-column refusals (expect 17), unexpected roles {4} (expect 0) -> {5}" -f $n[0], $n[1], $d[0], $d[1], $u, $(if ($okGrants) { 'OK' } else { 'DIFFERS' }))

# ---- 5. verification (impersonation) and live test as the new login
Write-Output ''; Write-Output '--- 5. Verification ---'
$cn.Close(); $cn = Open-Admin 'McLabor'
$v = @(Query $cn (ReviewedSql 'verify-readonly-login.sql') 300)
$checks = @(
    @{ n = 'runs as mclabor_web_read in McLabor';            t = { param($r) $r.Count -eq 1 -and "$($r[0][0])" -ieq 'mclabor_web_read' -and "$($r[0][2])" -ieq 'McLabor' } },
    @{ n = 'no server role';                                 t = { param($r) $r.Count -eq 8 -and -not ($r | Where-Object { [int]$_[1] -ne 0 }) } },
    @{ n = 'only database role mclabor_web_readonly';        t = { param($r) $r.Count -eq 1 -and "$($r[0][0])" -ieq 'mclabor_web_readonly' } },
    @{ n = 'database permissions: CONNECT (+ key-definition defaults)'; t = { param($r) $s = @($r | ForEach-Object { "$($_[0])".ToUpper() }); ($s -contains 'CONNECT') -and -not ($s | Where-Object { $_ -notin @('CONNECT', 'VIEW ANY COLUMN ENCRYPTION KEY DEFINITION', 'VIEW ANY COLUMN MASTER KEY DEFINITION') }) } },
    @{ n = 'server permissions: CONNECT SQL only';           t = { param($r) $r.Count -eq 1 -and "$($r[0][0])" -ieq 'CONNECT SQL' } },
    @{ n = 'no write right on any table or view';            t = { param($r) $r.Count -eq 0 } },
    @{ n = 'no executable procedure or function';            t = { param($r) $r.Count -eq 1 -and [int]$r[0][0] -eq 0 } },
    @{ n = '288 readable approved columns';                  t = { param($r) $r.Count -eq 1 -and [int]$r[0][0] -eq 288 } },
    @{ n = '17 sensitive columns, none readable';            t = { param($r) $r.Count -eq 17 -and -not ($r | Where-Object { [int]$_[1] -ne 0 }) } },
    @{ n = 'no readable table outside the approved list';    t = { param($r) $r.Count -eq 0 } },
    @{ n = 'sees only master, McLabor, tempdb';              t = { param($r) $s = @($r | ForEach-Object { "$($_[0])".ToLower() } | Sort-Object); ($s -join ',') -eq 'master,mclabor,tempdb' } }
)
$failed = 0
for ($i = 0; $i -lt $checks.Count; $i++) {
    $rows = @(); if ($i -lt $v.Count) { $rows = @($v[$i].Rows) }
    $ok = $false; try { $ok = [bool](& $checks[$i].t $rows) } catch { $ok = $false }
    if (-not $ok) { $failed++ }
    Say ("  {0} {1}" -f $(if ($ok) { 'PASS' } else { 'FAIL' }), $checks[$i].n)
    if ($i -lt $v.Count) { $report.Add("## Verification $($i + 1): $($checks[$i].n) -> $(if ($ok) { 'PASS' } else { 'FAIL' })"); $report.Add(''); $report.Add((MdTable $v[$i])); $report.Add('') }
}
# live test: sign in AS the new login (locally) - allowed read, refused reads, refused writes on zero rows
$ro = New-Object System.Data.SqlClient.SqlConnection "Server=$Instance;Database=McLabor;User ID=mclabor_web_read;Password=$password;Application Name=mclabor-onetime-setup-test;Connect Timeout=15;"
$ro.Open()
function Probe($sql, $expectRefused, $label) {
    $cmd = $script:ro.CreateCommand(); $cmd.CommandText = $sql; $cmd.CommandTimeout = 60
    try { $r = $cmd.ExecuteScalar(); $outcome = "allowed (result $r)"; $pass = -not $expectRefused }
    catch {
        $ex = $_.Exception; while ($ex -and -not ($ex -is [System.Data.SqlClient.SqlException])) { $ex = $ex.InnerException }
        $num = if ($ex) { $ex.Number } else { -1 }
        $outcome = "refused (SQL Server error $num)"; $pass = $expectRefused -and ($num -in 229, 230)
    }
    if (-not $pass) { $script:failed++ }
    Say ("  {0} live test as mclabor_web_read: {1} -> {2}" -f $(if ($pass) { 'PASS' } else { 'FAIL' }), $label, $outcome)
}
Probe 'SELECT COUNT(FeatureID) FROM dbo.tblFeature' $false 'read an approved column (row count only)'
Probe 'SELECT COUNT(*) FROM dbo.tblFeature' $true 'COUNT(*) over the whole table (touches unapproved columns)'
Probe 'SELECT TOP (1) SSNum FROM dbo.tblEmployee' $true 'read the SSN column'
Probe 'SELECT TOP (1) * FROM dbo.tblOfficeStaff' $true 'read the staff table including its password column'
Probe 'UPDATE dbo.tblFeature SET FeatureSort = FeatureSort WHERE 1 = 0' $true 'UPDATE (zero rows)'
Probe 'DELETE FROM dbo.tblFeature WHERE 1 = 0' $true 'DELETE (zero rows)'
Probe "INSERT INTO dbo.tblFeature (FeatureTitle) SELECT N'x' WHERE 1 = 0" $true 'INSERT (zero rows)'
Probe 'SELECT COUNT(*) FROM msdb.dbo.sysjobs' $true 'read a system table of another database (job list)'
$ro.Close()
Say $(if ($failed -eq 0) { 'VERIFICATION PASSED: the login can read the approved columns and nothing else, and cannot change anything.' } else { "VERIFICATION: $failed check(s) FAILED - send this report to the owner before the login is used." })
$cn.Close(); $cn = $null

# ---- 6. certificate for verified encrypted connections
Write-Output ''; Write-Output '--- 6. Server certificate ---'
$elevated = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
$instId = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Microsoft SQL Server\Instance Names\SQL' -ErrorAction SilentlyContinue).SQLEXPRESS
$netKey = "HKLM:\SOFTWARE\Microsoft\Microsoft SQL Server\$instId\MSSQLServer\SuperSocketNetLib"
$thumb = if ($instId) { (Get-ItemProperty $netKey -ErrorAction SilentlyContinue).Certificate } else { '' }
$cert = if ($thumb) { Get-ChildItem Cert:\LocalMachine\My | Where-Object { $_.Thumbprint -ieq $thumb } } else { $null }
if ($SkipCertificate) { Say 'Certificate step skipped (-SkipCertificate).' }
elseif ($cert) { Say "Certificate: SQL Server already uses certificate $($cert.Thumbprint) ($($cert.Subject), valid to $($cert.NotAfter.ToString('yyyy-MM-dd')))." }
elseif (-not $elevated) { Say 'Certificate step SKIPPED: this window is not running as administrator. Run RUN-ME.cmd again later with "Run as administrator" when nobody is in Access; everything already done is kept.' }
else {
    Write-Output 'Installs a certificate so the office PC can verify it talks to this server. SQL Server restarts for about one minute;'
    Write-Output 'anyone in the Access application is disconnected during that minute and reconnects. No database or record is touched.'
    if (Ask 'Install the server certificate and restart SQL Server now?') {
        & (Join-Path $here 'certificate-setup.ps1')
        $thumb = (Get-ItemProperty $netKey).Certificate
        $cert = Get-ChildItem Cert:\LocalMachine\My | Where-Object { $_.Thumbprint -ieq $thumb }
        Say "Certificate installed: $($cert.Thumbprint), valid to $($cert.NotAfter.ToString('yyyy-MM-dd')); SQL Server restarted."
    } else { Say 'Certificate step declined for now; can be run later with RUN-ME.cmd as administrator.' }
}
if ($cert) {
    $cerOut = Join-Path $results "$env:COMPUTERNAME-sqlserver.cer"
    [IO.File]::WriteAllBytes($cerOut, $cert.Export([Security.Cryptography.X509Certificates.X509ContentType]::Cert))
    Say "Public certificate exported for the office PC: results\$env:COMPUTERNAME-sqlserver.cer (public part only, no private key)."
}

# ---- 7. hand the password to the office PC without anyone reading it
Write-Output ''; Write-Output '--- 7. Password hand-off ---'
$key = Join-Path $here 'transfer-key.cer'
$cmsOut = Join-Path $results 'mclabor_web_read.password.cms'
$handed = $false
if (Test-Path $key) {
    try {
        Protect-CmsMessage -To $key -Content $password -OutFile $cmsOut
        if ((Get-Item $cmsOut).Length -gt 100) { $handed = $true }
    } catch { Write-Output "Encryption to the transfer key failed: $($_.Exception.Message)" }
}
if ($handed) { Say 'The new password was encrypted to the office PC''s transfer key -> results\mclabor_web_read.password.cms (only the office PC can open it; safe to copy or e-mail).' }
else {
    Say 'The new password could NOT be encrypted for the office PC. It is shown ONCE below; write it down and hand it in person to whoever runs the office PC (never e-mail or chat).'
    Write-Output ''; Write-Output "    mclabor_web_read password:  $password"; Write-Output ''
    Read-Host 'Press Enter when you have written it down' | Out-Null
}
$password = $null; [GC]::Collect()

# ---- report
$report.Insert(2, '## Summary'); $report.Insert(3, '')
$k = 4; foreach ($s in $summary) { $report.Insert($k, "- $s"); $k++ }; $report.Insert($k, '')
$path = Join-Path $results "setup-report-$stamp.md"
[IO.File]::WriteAllText($path, ($report -join "`n"), (New-Object Text.UTF8Encoding $false))
try { Set-Clipboard -Value ($report -join "`n"); $clip = ' (also on the clipboard)' } catch { $clip = '' }
Write-Output ''; Write-Output "Report: $path$clip. Give the whole 'results' folder back to the MC Labor project (it contains no password in clear and no data)."
exit $(if ($failed -eq 0 -and $okGrants) { 0 } else { 2 })
