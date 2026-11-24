# NOT RUN YET. Needs the owner's approval and an administrator PowerShell window.
# Target: the STAGING copy on DEV-PC only.
# Reviewed against Microsoft's "Certificate requirements for SQL Server" (see docs/certificate-script-review.md).
#
# What it does on this PC (DEV-PC), in order:
#   1. Creates a certificate named after this computer (CN=DEV-PC, also valid for "localhost"), valid 5 years.
#   2. CHECKS the certificate meets SQL Server's requirements. If any check fails it deletes the certificate and stops.
#   3. Lets the SQL Server service account read the certificate's private key, and CHECKS that worked.
#   4. Adds the certificate to this PC's Trusted Root store so programs on this PC can verify it.
#   5. Only then tells the SQLEXPRESS instance to use it (one registry value). ForceEncryption is left as it is (off).
#   6. Restarts the SQL Server (SQLEXPRESS) service. Anyone using Access is disconnected for about a minute.
#   7. If SQL Server does not come back within 90 seconds, it UNDOES step 5, starts SQL Server again and removes the certificate.
#
# It does not touch any database, table, record, login, permission, port or firewall rule.
# Run it only when nobody is using the Access application.

#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSEdition -ne 'Desktop') { throw 'Run this in Windows PowerShell (powershell.exe), not PowerShell 7 (pwsh). Nothing was changed.' }
# SAFETY: this run is for the STAGING copy on DEV-PC only. It refuses to run on any other computer (for example LIVE-HOST).
$expectedComputer = 'DEV-PC'
if ($env:COMPUTERNAME -ne $expectedComputer) { throw "This script is set up for $expectedComputer but this computer is $env:COMPUTERNAME. Nothing was changed." }
$instance = 'SQLEXPRESS'
$service  = "MSSQL`$$instance"
$computer = $env:COMPUTERNAME
$instId   = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Microsoft SQL Server\Instance Names\SQL').$instance
if (-not $instId) { throw "SQL Server instance '$instance' not found on this PC." }
$netKey   = "HKLM:\SOFTWARE\Microsoft\Microsoft SQL Server\$instId\MSSQLServer\SuperSocketNetLib"
$account  = (Get-CimInstance Win32_Service -Filter "Name='$service'").StartName
$old      = (Get-ItemProperty $netKey).Certificate
$state    = Join-Path $PSScriptRoot 'certificate-setup-state.json'
"Instance $instId, service account '$account', certificate currently configured: '$old'"

# 1. certificate. A legacy CSP with KeySpec=KeyExchange is required: SQL Server cannot use keys in a Key Storage Provider.
$cert = New-SelfSignedCertificate -Subject "CN=$computer" -DnsName $computer, 'localhost' `
    -CertStoreLocation Cert:\LocalMachine\My -FriendlyName "SQL Server $instance ($computer)" `
    -KeyAlgorithm RSA -KeyLength 2048 -KeySpec KeyExchange -KeyExportPolicy NonExportable `
    -Provider 'Microsoft RSA SChannel Cryptographic Provider' -HashAlgorithm SHA256 `
    -KeyUsage DigitalSignature, KeyEncipherment `
    -TextExtension @('2.5.29.37={text}1.3.6.1.5.5.7.3.1') -NotAfter (Get-Date).AddYears(5)

function Remove-NewCertificate { Get-ChildItem Cert:\LocalMachine\My, Cert:\LocalMachine\Root | Where-Object Thumbprint -eq $cert.Thumbprint | Remove-Item -ErrorAction SilentlyContinue }

try {
    # 2. requirement checks BEFORE SQL Server is told about the certificate
    $csp = $cert.PrivateKey.CspKeyContainerInfo
    if (-not $csp)                                   { throw 'Private key is not in a legacy CSP (KeySpec would be 0).' }
    if ("$($csp.KeyNumber)" -ne 'Exchange')          { throw "KeySpec is '$($csp.KeyNumber)', SQL Server needs Exchange (AT_KEYEXCHANGE)." }
    if (-not ($cert.EnhancedKeyUsageList.ObjectId -contains '1.3.6.1.5.5.7.3.1')) { throw 'Server Authentication EKU is missing.' }
    if (-not ($cert.DnsNameList.Unicode -contains $computer))                   { throw "Certificate does not list the name $computer." }
    if ((Get-Date) -lt $cert.NotBefore -or (Get-Date) -gt $cert.NotAfter)        { throw 'Certificate is not valid at the current date and time.' }

    # 3. private-key read access for the SQL Server service account
    $keyFile = Join-Path "$env:ProgramData\Microsoft\Crypto\RSA\MachineKeys" $csp.UniqueKeyContainerName
    if (-not (Test-Path $keyFile)) { throw "Private key file not found: $keyFile" }
    if ($account -notin 'LocalSystem', 'NT AUTHORITY\SYSTEM') {
        icacls $keyFile /grant "${account}:R" | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Could not grant '$account' read access to the private key." }
        $short = ($account -split '\\')[-1]
        if (((icacls $keyFile) -join "`n") -notmatch [regex]::Escape($short)) { throw "Read access for '$account' is not on the private key." }
    }

    # 4. trust it on this PC (public part only) - done before SQL Server is told about the certificate, so a failure
    #    here still leaves SQL Server untouched
    $cer = Join-Path $env:TEMP "$computer-sqlserver.cer"
    Export-Certificate -Cert $cert -FilePath $cer | Out-Null
    Import-Certificate -FilePath $cer -CertStoreLocation Cert:\LocalMachine\Root | Out-Null
    Remove-Item $cer
    if (-not (Get-ChildItem Cert:\LocalMachine\Root | Where-Object Thumbprint -eq $cert.Thumbprint)) { throw 'The certificate did not arrive in the Trusted Root store.' }
} catch {
    Remove-NewCertificate
    throw "Stopped before changing SQL Server. Nothing was changed. Reason: $_"
}

# record what is about to change, so it can be undone later
@{ thumbprint = $cert.Thumbprint; previousRegistryValue = "$old"; instance = $instId; date = (Get-Date).ToString('s') } | ConvertTo-Json | Set-Content $state -Encoding utf8

# 5. point the instance at the certificate (the only change to SQL Server's own settings)
Set-ItemProperty $netKey -Name Certificate -Value $cert.Thumbprint.ToLower()

# 6. restart SQL Server so it loads the certificate; 7. undo automatically if it does not come back
$running = $false
try {
    Restart-Service $service -Force
    (Get-Service $service).WaitForStatus('Running', [TimeSpan]::FromSeconds(90))
    $running = $true
} catch { }
if (-not $running) {
    Set-ItemProperty $netKey -Name Certificate -Value "$old"
    Start-Service $service
    (Get-Service $service).WaitForStatus('Running', [TimeSpan]::FromSeconds(90))
    Remove-NewCertificate
    throw "SQL Server did not start with the new certificate. The previous setting was restored and SQL Server is running again (status: $((Get-Service $service).Status))."
}
"Done. SQL Server is running with certificate $($cert.Thumbprint) (expires $($cert.NotAfter.ToString('yyyy-MM-dd'))). Details saved in $state"

# ---- UNDO LATER (run as administrator) ---------------------------------------------------------
# $s = Get-Content '<path>\certificate-setup-state.json' | ConvertFrom-Json
# Set-ItemProperty "HKLM:\SOFTWARE\Microsoft\Microsoft SQL Server\$($s.instance)\MSSQLServer\SuperSocketNetLib" -Name Certificate -Value $s.previousRegistryValue
# Restart-Service 'MSSQL$SQLEXPRESS' -Force
# Get-ChildItem Cert:\LocalMachine\My, Cert:\LocalMachine\Root | Where-Object Thumbprint -eq $s.thumbprint | Remove-Item
