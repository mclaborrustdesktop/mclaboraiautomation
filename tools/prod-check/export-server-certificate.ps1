# Run ON THE SQL SERVER (LIVE-HOST) after proposed-certificate-setup.ps1 has installed its certificate there.
# Exports the certificate's PUBLIC part (no private key) to a .cer file for the web PC to trust. Read-only.
#   powershell -ExecutionPolicy Bypass -File export-server-certificate.ps1 -Out C:\temp\LIVE-HOST-sqlserver.cer
param([string]$Instance = 'SQLEXPRESS', [string]$Out = "$env:TEMP\$env:COMPUTERNAME-sqlserver.cer")
$ErrorActionPreference = 'Stop'
$instId = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Microsoft SQL Server\Instance Names\SQL').$Instance
if (-not $instId) { throw "SQL Server instance '$Instance' not found on this computer." }
$thumb = (Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Microsoft SQL Server\$instId\MSSQLServer\SuperSocketNetLib").Certificate
if (-not $thumb) { throw 'SQL Server has no certificate configured on this instance (proposed-certificate-setup.ps1 has not been run here).' }
$cert = Get-ChildItem Cert:\LocalMachine\My | Where-Object { $_.Thumbprint -eq $thumb }
if (-not $cert) { throw "Configured certificate $thumb not found in the computer store." }
[IO.File]::WriteAllBytes($Out, $cert.Export([Security.Cryptography.X509Certificates.X509ContentType]::Cert))
Write-Output "Exported public certificate: $Out"
Write-Output "  subject $($cert.Subject), valid to $($cert.NotAfter.ToString('yyyy-MM-dd')), thumbprint $($cert.Thumbprint)"
Write-Output 'Copy this file to the web PC and run tools\prod-check\trust-server-certificate.ps1 there (administrator).'
