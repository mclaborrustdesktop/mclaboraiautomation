# NOT RUN YET. Run on the WEB PC (DEV-PC) as administrator, once the live server's public certificate file exists.
# Adds that one certificate to this PC's Trusted Root store so the website can verify the live server. It changes
# nothing else on this PC and nothing on the server. Undo: remove the certificate from Cert:\LocalMachine\Root.
#   powershell -ExecutionPolicy Bypass -File tools\prod-check\trust-server-certificate.ps1 -CerFile C:\temp\LIVE-HOST-sqlserver.cer -ExpectedName LIVE-HOST
#Requires -RunAsAdministrator
param([Parameter(Mandatory = $true)][string]$CerFile, [string]$ExpectedName = 'LIVE-HOST')
$ErrorActionPreference = 'Stop'
if (-not (Test-Path $CerFile)) { throw "Certificate file not found: $CerFile" }
$cert = New-Object Security.Cryptography.X509Certificates.X509Certificate2($CerFile)
if ($cert.HasPrivateKey) { throw 'This file contains a private key. Only the public .cer export may be trusted here. Nothing was changed.' }
if (-not ($cert.DnsNameList.Unicode -contains $ExpectedName) -and $cert.Subject -ne "CN=$ExpectedName") { throw "The certificate is for '$($cert.Subject)', not for $ExpectedName. Nothing was changed." }
if ((Get-Date) -gt $cert.NotAfter) { throw 'The certificate has expired. Nothing was changed.' }
$existing = Get-ChildItem Cert:\LocalMachine\Root | Where-Object { $_.Thumbprint -eq $cert.Thumbprint }
if ($existing) { Write-Output "Already trusted: $($cert.Subject) ($($cert.Thumbprint))"; exit 0 }
$store = New-Object Security.Cryptography.X509Certificates.X509Store('Root', 'LocalMachine')
$store.Open('ReadWrite'); $store.Add($cert); $store.Close()
Write-Output "Trusted on $env:COMPUTERNAME: $($cert.Subject), valid to $($cert.NotAfter.ToString('yyyy-MM-dd')), thumbprint $($cert.Thumbprint)"
Write-Output 'Next: tools\prod-check\run-prodcheck-production.ps1'
