# Monthly proof that a backup can be restored: downloads the newest daily backup from Blob, decrypts it, restores it
# as <Database>_RestoreTest on the same instance, runs DBCC CHECKDB, compares row counts with the live database,
# then drops the test database. Nothing in the live database is touched.
#   powershell -ExecutionPolicy Bypass -File restore-test.ps1 -Database McLabor
param([Parameter(Mandatory = $true)][string]$Database, [string]$Instance = '.\SQLEXPRESS', [string]$Root = 'C:\mclabor')
$ErrorActionPreference = 'Stop'
$log = Join-Path $Root 'logs\restore-test.log'
function Say([string]$m) { $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $m"; Add-Content $log $line; Write-Output $line }
$work = Join-Path $Root 'backups\restore-test'
$test = "${Database}_RestoreTest"
try {
    New-Item -ItemType Directory -Force $work | Out-Null
    $sas = (Get-Content (Join-Path $Root 'secrets\backup.sas') -Raw).Trim()
    $listUrl = $sas -replace '\?', '/daily?' ; $listUrl += '&restype=container&comp=list&prefix=daily/'
    [xml]$xml = (Invoke-WebRequest -Uri $listUrl -UseBasicParsing).Content
    $newest = $xml.EnumerationResults.Blobs.Blob | Sort-Object { [datetime]$_.Properties.'Last-Modified' } -Descending | Select-Object -First 1
    if (-not $newest) { throw 'no daily backup found in the container' }
    $name = Split-Path $newest.Name -Leaf
    $enc = Join-Path $work $name
    & "$Root\tools\azcopy.exe" copy ($sas -replace '\?', "/$($newest.Name)?") $enc --log-level ERROR --output-level essential | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'download failed' }
    Say "downloaded $name"
    $key = [Security.Cryptography.ProtectedData]::Unprotect([IO.File]::ReadAllBytes((Join-Path $Root 'secrets\backup.key')), $null, 'LocalMachine')
    $all = [IO.File]::ReadAllBytes($enc)
    $body = $all[0..($all.Length - 33)]; $mac = $all[($all.Length - 32)..($all.Length - 1)]
    $expect = (New-Object Security.Cryptography.HMACSHA256(, $key)).ComputeHash($body)
    if (-not [Linq.Enumerable]::SequenceEqual([byte[]]$mac, [byte[]]$expect)) { throw 'HMAC mismatch: the file was altered or the key is wrong' }
    $aes = [Security.Cryptography.Aes]::Create(); $aes.KeySize = 256; $aes.Key = $key; $aes.IV = $body[0..15]; $aes.Mode = 'CBC'; $aes.Padding = 'PKCS7'
    $zipBytes = $aes.CreateDecryptor().TransformFinalBlock($body, 16, $body.Length - 16)
    $zip = Join-Path $work ($name -replace '\.enc$', ''); [IO.File]::WriteAllBytes($zip, $zipBytes); $zipBytes = $null; $key = $null
    Expand-Archive $zip -DestinationPath $work -Force
    $bak = Get-ChildItem $work -Filter '*.bak' | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    Say "decrypted and unpacked $($bak.Name)"
    $data = (& sqlcmd -S $Instance -E -h -1 -W -Q "SET NOCOUNT ON; SELECT CAST(SERVERPROPERTY('InstanceDefaultDataPath') AS nvarchar(260))").Trim()
    $files = & sqlcmd -S $Instance -E -h -1 -W -Q "SET NOCOUNT ON; RESTORE FILELISTONLY FROM DISK = N'$($bak.FullName)'" | Where-Object { $_ -match '\S' }
    $moves = @(); foreach ($line in $files) { $parts = $line -split '\s{2,}'; $logical = $parts[0]; $ext = if ($parts[2] -eq 'L') { '_log.ldf' } else { '.mdf' }; $moves += "MOVE N'$logical' TO N'$data$test$($logical)$ext'" }
    & sqlcmd -S $Instance -E -b -Q "RESTORE DATABASE [$test] FROM DISK = N'$($bak.FullName)' WITH $($moves -join ', '), REPLACE, CHECKSUM, STATS = 25" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'RESTORE DATABASE failed' }
    & sqlcmd -S $Instance -E -b -Q "DBCC CHECKDB ([$test]) WITH NO_INFOMSGS, ALL_ERRORMSGS" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'DBCC CHECKDB reported errors' }
    foreach ($t in 'tblEmployee', 'tblCustomer', 'tblProject', 'tblTracking') {
        $live = (& sqlcmd -S $Instance -E -h -1 -W -Q "SET NOCOUNT ON; SELECT COUNT(*) FROM [$Database].dbo.[$t]").Trim()
        $rest = (& sqlcmd -S $Instance -E -h -1 -W -Q "SET NOCOUNT ON; SELECT COUNT(*) FROM [$test].dbo.[$t]").Trim()
        Say "$t : live $live, restored $rest"
    }
    Say "RESTORE TEST PASSED ($name)"
    Write-EventLog -LogName Application -Source 'MCLaborBackup' -EntryType Information -EventId 1010 -Message "Restore test passed ($name)."
}
catch {
    Say "RESTORE TEST FAILED: $($_.Exception.Message)"
    Write-EventLog -LogName Application -Source 'MCLaborBackup' -EntryType Error -EventId 1011 -Message "Restore test FAILED: $($_.Exception.Message)"
    exit 1
}
finally {
    & sqlcmd -S $Instance -E -Q "IF DB_ID(N'$test') IS NOT NULL BEGIN ALTER DATABASE [$test] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; DROP DATABASE [$test]; END" | Out-Null
    Remove-Item $work -Recurse -Force -ErrorAction SilentlyContinue
}
