# Builds deploy\vm\azure\cloudshell-package.zip: the files to upload to Azure Cloud Shell (no secrets, no data).
#   powershell -ExecutionPolicy Bypass -File deploy\vm\azure\make-package.ps1
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$zip = Join-Path $here 'cloudshell-package.zip'
$files = 'provision-vm.ps1', 'preflight-cloudshell.ps1', 'temporary-rdp.ps1', 'cleanup-staging.ps1', 'budget.bicep', 'lifecycle.json', 'dcr-events.json', 'CLOUDSHELL.md' | ForEach-Object { Join-Path $here $_ }
foreach ($f in $files) { if (-not (Test-Path $f)) { throw "missing $f" } }
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path $files -DestinationPath $zip
Write-Output "Package: $zip ($([math]::Round((Get-Item $zip).Length / 1KB)) KB): $((Split-Path $files -Leaf) -join ', ')"
