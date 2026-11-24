# Stores the PRODUCTION read-only login's password on this PC, encrypted with Windows DPAPI for the Windows account
# that runs it. The password is typed once at a hidden prompt and is never displayed, logged or written in clear.
#   powershell -ExecutionPolicy Bypass -File tools\production\store-db-password.ps1
# Use it after the administrator has created the login mclabor_web_read on the live server with
# tools\prod-check\proposed-grants-production.sql (the administrator chooses the password there and hands it over
# out of band - never by e-mail or chat).
# The website's production start script and run-readonly.ps1 -EnvFile backend\.env.production read it from here:
#   %LOCALAPPDATA%\MCLabor\production-mclabor_web_read.dpapi
param([switch]$Replace)
$ErrorActionPreference = 'Stop'
$secretDir  = Join-Path $env:LOCALAPPDATA 'MCLabor'
$secretFile = Join-Path $secretDir 'production-mclabor_web_read.dpapi'
if ((Test-Path $secretFile) -and -not $Replace) { throw "A stored production password already exists ($secretFile). Use -Replace to overwrite it." }
$one = Read-Host -AsSecureString 'Password for SQL login mclabor_web_read on the LIVE server (typing is hidden)'
$two = Read-Host -AsSecureString 'Type it again'
$p1 = (New-Object System.Net.NetworkCredential('', $one)).Password
$p2 = (New-Object System.Net.NetworkCredential('', $two)).Password
if ($p1 -ne $p2) { throw 'The two entries do not match. Nothing was stored.' }
if ($p1.Length -lt 16) { throw 'The password is shorter than 16 characters. Nothing was stored.' }
$p1 = $null; $p2 = $null
New-Item -ItemType Directory -Force $secretDir | Out-Null
ConvertFrom-SecureString $one | Set-Content -Path $secretFile -Encoding ascii
Write-Output "Stored (encrypted for $env:USERDOMAIN\$env:USERNAME on $env:COMPUTERNAME): $secretFile"
Write-Output 'Next: tools\prod-check\run-prodcheck-production.ps1 must end with READ-ONLY CONNECTION VERIFIED before the website is pointed at the live server.'
