# Nightly backup of a SQL Server Express database to Azure Blob storage, encrypted before it leaves the VM.
#   powershell -ExecutionPolicy Bypass -File backup-sql.ps1 -Database McLabor [-Monthly]
# Steps: BACKUP DATABASE ... WITH CHECKSUM -> RESTORE VERIFYONLY -> zip -> AES-256 (CBC) + HMAC-SHA256 with a key that
# lives in C:\mclabor\secrets\backup.key (DPAPI-protected on this VM) AND in the company's password safe (printed once
# by -ShowKey; without it a backup cannot be opened anywhere) -> upload with AzCopy using a write-only SAS token from
# C:\mclabor\secrets\backup.sas -> keep 7 days locally. Daily files go to daily/, -Monthly files to monthly/; the
# storage account's lifecycle rule deletes daily after 35 days and monthly after 12 months. Every step is logged;
# a failure writes an Error to the Application event log (source MCLaborBackup) for the monitoring alert.
param(
    [Parameter(Mandatory = $true)][string]$Database,
    [string]$Instance = '.\SQLEXPRESS',
    [string]$Root = 'C:\mclabor',
    [switch]$Monthly,
    [switch]$ShowKey,
    [switch]$InitKey
)
$ErrorActionPreference = 'Stop'
$log = Join-Path $Root 'logs\backup.log'
$local = Join-Path $Root 'backups'
$keyFile = Join-Path $Root 'secrets\backup.key'
$sasFile = Join-Path $Root 'secrets\backup.sas'
function Say([string]$m) { $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $m"; Add-Content $log $line; Write-Output $line }
if (-not ([System.Diagnostics.EventLog]::SourceExists('MCLaborBackup'))) { New-EventLog -LogName Application -Source 'MCLaborBackup' }

if ($InitKey) {
    if (Test-Path $keyFile) { throw "A key already exists at $keyFile." }
    $bytes = New-Object byte[] 32; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $protected = [Security.Cryptography.ProtectedData]::Protect($bytes, $null, 'LocalMachine')
    [IO.File]::WriteAllBytes($keyFile, $protected)
    Write-Output "Backup key created. SAVE THIS in the company password safe now (it is shown once):"
    Write-Output ([Convert]::ToBase64String($bytes)); return
}
function Get-Key {
    if (-not (Test-Path $keyFile)) { throw 'No backup key. Run with -InitKey first and store the key off the VM.' }
    return [Security.Cryptography.ProtectedData]::Unprotect([IO.File]::ReadAllBytes($keyFile), $null, 'LocalMachine')
}
if ($ShowKey) { Write-Output ([Convert]::ToBase64String((Get-Key))); return }

try {
    New-Item -ItemType Directory -Force $local | Out-Null
    $stamp = Get-Date -Format 'yyyyMMdd-HHmm'
    $bak = Join-Path $local "$Database-$stamp.bak"
    Say "backup $Database on $Instance -> $bak"
    & sqlcmd -S $Instance -E -b -Q "BACKUP DATABASE [$Database] TO DISK = N'$bak' WITH CHECKSUM, INIT, FORMAT, STATS = 25" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'BACKUP DATABASE failed' }
    & sqlcmd -S $Instance -E -b -Q "RESTORE VERIFYONLY FROM DISK = N'$bak' WITH CHECKSUM" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'RESTORE VERIFYONLY failed: the backup file is not usable' }
    Say "verified"
    $zip = "$bak.zip"; Compress-Archive -Path $bak -DestinationPath $zip -Force
    # encrypt: IV (16) + ciphertext, then HMAC-SHA256 over both appended (32)
    $key = Get-Key
    $aes = [Security.Cryptography.Aes]::Create(); $aes.KeySize = 256; $aes.Key = $key; $aes.GenerateIV(); $aes.Mode = 'CBC'; $aes.Padding = 'PKCS7'
    $plain = [IO.File]::ReadAllBytes($zip)
    $cipher = $aes.CreateEncryptor().TransformFinalBlock($plain, 0, $plain.Length)
    $body = $aes.IV + $cipher
    $mac = (New-Object Security.Cryptography.HMACSHA256(, $key)).ComputeHash($body)
    $enc = "$zip.enc"; [IO.File]::WriteAllBytes($enc, $body + $mac)
    $plain = $null; $cipher = $null; $key = $null
    Say "encrypted $([math]::Round((Get-Item $enc).Length / 1MB)) MB"
    if (-not (Test-Path $sasFile)) { throw "No upload token at $sasFile (a write-only SAS URL for the backup container)." }
    $sas = (Get-Content $sasFile -Raw).Trim()
    $folder = if ($Monthly) { 'monthly' } else { 'daily' }
    $dest = $sas -replace '\?', "/$folder/$(Split-Path $enc -Leaf)?"
    & "$Root\tools\azcopy.exe" copy $enc $dest --put-md5 --log-level ERROR --output-level essential | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'upload failed (AzCopy)' }
    Say "uploaded to $folder/"
    Get-ChildItem $local -File | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-7) } | Remove-Item -Force
    Remove-Item $bak, $zip -Force
    Say "done"
    Write-EventLog -LogName Application -Source 'MCLaborBackup' -EntryType Information -EventId 1000 -Message "Backup of $Database uploaded ($folder)."
}
catch {
    Say "FAILED: $($_.Exception.Message)"
    Write-EventLog -LogName Application -Source 'MCLaborBackup' -EntryType Error -EventId 1001 -Message "Backup of $Database FAILED: $($_.Exception.Message)"
    exit 1
}
