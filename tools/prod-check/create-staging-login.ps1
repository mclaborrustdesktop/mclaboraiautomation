# Creates the restricted read-only login on the STAGING copy (DEV-PC\SQLEXPRESS) by running proposed-grants.sql.
# Approved by the owner on 2026-11-20 ("option A").
#
# The password is generated here, at random. It is never displayed, never written to a log and never placed in
# the SQL text (it is sent as a parameter). It is saved encrypted with Windows DPAPI: only the Windows account
# that ran this script, on this PC, can read it back.
#
# Run with Windows PowerShell 5.1, as the Windows account that administers SQL Server. No elevation needed.
$ErrorActionPreference = 'Stop'

$expectedServer = 'DEV-PC\SQLEXPRESS'
$loginName      = 'mclabor_web_read'
$here           = Split-Path -Parent $MyInvocation.MyCommand.Path
$sqlFile        = Join-Path $here 'proposed-grants.sql'
$secretDir      = Join-Path $env:LOCALAPPDATA 'MCLabor'
$secretFile     = Join-Path $secretDir 'staging-mclabor_web_read.dpapi'

if ($env:COMPUTERNAME -ne 'DEV-PC') { throw "This script only runs on DEV-PC. Nothing was created." }
if (Test-Path $secretFile) { throw "A stored password already exists ($secretFile). Nothing was created." }

$conn = New-Object System.Data.SqlClient.SqlConnection("Server=$expectedServer;Database=master;Integrated Security=True;Encrypt=True;TrustServerCertificate=False;Application Name=MC Labor staging login setup")
$conn.Open()
try {
    function Scalar([string]$sql) { $c = $conn.CreateCommand(); $c.CommandText = $sql; return $c.ExecuteScalar() }

    $actual = [string](Scalar "SELECT CAST(SERVERPROPERTY('ServerName') AS nvarchar(128))")
    if ($actual -ne $expectedServer) { throw "Wrong server: '$actual' answered. Nothing was created." }
    if ((Scalar "SELECT IS_SRVROLEMEMBER('sysadmin')") -ne 1) { throw "This Windows account is not a SQL Server administrator. Nothing was created." }
    if ((Scalar "SELECT COUNT(*) FROM sys.server_principals WHERE name = N'$loginName'") -ne 0) { throw "The login $loginName already exists. Nothing was changed." }

    # Random 40-character password: letters, digits, '-' and '_' (64 symbols, so no bias from the random bytes).
    $alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_'
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    do {
        $bytes = New-Object byte[] 40
        $rng.GetBytes($bytes)
        $plain = -join ($bytes | ForEach-Object { $alphabet[$_ -band 63] })
    } until ($plain -cmatch '[A-Z]' -and $plain -cmatch '[a-z]' -and $plain -match '[0-9]')

    # Save the encrypted copy BEFORE creating the login, so a login can never exist without its password.
    New-Item -ItemType Directory -Force $secretDir | Out-Null
    $secure = New-Object System.Security.SecureString
    foreach ($ch in $plain.ToCharArray()) { $secure.AppendChar($ch) }
    ConvertFrom-SecureString $secure | Set-Content -Path $secretFile -Encoding ascii

    try {
        $batches = [regex]::Split((Get-Content $sqlFile -Raw), '(?im)^\s*GO\s*$') | Where-Object { $_.Trim() }
        $placeholderLine = "DECLARE @password nvarchar(128) = N'<<TYPE-A-LONG-PASSWORD-HERE>>';"
        if (-not $batches[0].Contains($placeholderLine)) { throw "proposed-grants.sql is not in the expected form." }

        # Batch 1 (the login): the password travels as a parameter, not as text.
        $cmd = $conn.CreateCommand()
        $cmd.CommandText = $batches[0].Replace($placeholderLine, '')
        $p = $cmd.Parameters.Add('@password', [System.Data.SqlDbType]::NVarChar, 128)
        $p.Value = $plain
        [void]$cmd.ExecuteNonQuery()
        Write-Output "Step 1 done: login $loginName created."

        # Batch 2 (user and role) switches to the McLabor database.
        $cmd = $conn.CreateCommand(); $cmd.CommandText = $batches[1]; [void]$cmd.ExecuteNonQuery()
        if ([string](Scalar 'SELECT DB_NAME()') -ne 'McLabor') { throw "Not in the McLabor database after step 2." }
        Write-Output "Step 2 done: database user and role created."

        # Batch 3 (the 33 GRANT SELECT lines).
        $cmd = $conn.CreateCommand(); $cmd.CommandText = $batches[2]; [void]$cmd.ExecuteNonQuery()
        Write-Output "Step 3 done: read permissions granted."

        # Batch 4 (verification, read-only).
        $cmd = $conn.CreateCommand(); $cmd.CommandText = $batches[3]
        $r = $cmd.ExecuteReader()
        if ($r.Read()) { Write-Output ("Step 4: column permissions = {0}, tables = {1}, permission = {2} / {3}  (expected 288, 33, SELECT / SELECT)" -f $r[0], $r[1], $r[2], $r[3]) }
        [void]$r.NextResult()
        $extra = @(); while ($r.Read()) { $extra += [string]$r[0] }
        $r.Close()
        if ($extra.Count) { Write-Output ("Step 4: UNEXPECTED extra roles: " + ($extra -join ', ')) } else { Write-Output "Step 4: the user is in no other role (expected)." }
    }
    catch {
        if ((Scalar "SELECT COUNT(*) FROM sys.server_principals WHERE name = N'$loginName'") -eq 0) { Remove-Item $secretFile -Force -Confirm:$false }
        throw
    }
    finally { $plain = $null; $bytes = $null }
}
finally { $conn.Close() }

Write-Output "Password stored encrypted (never displayed): $secretFile"
