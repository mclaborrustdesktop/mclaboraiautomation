# After a deployment: proves the real-data guards from outside the VM (run on any PC: from the office, the backend
# port must be unreachable and the public hostname must demand sign-in) and, on the VM itself, that the services answer.
#   powershell -ExecutionPolicy Bypass -File deploy\vm\smoke.ps1 -Site https://app.mclabor.example -Expect production
param([Parameter(Mandatory = $true)][string]$Site, [ValidateSet('staging', 'production')][string]$Expect = 'production', [string]$VmPrivateIp = '10.20.1.4')
$root = Resolve-Path (Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) '..\..')
$port = if ($Expect -eq 'production') { 8000 } else { 8100 }
& (Join-Path $root 'backend\.venv\Scripts\python.exe') (Join-Path $root 'tools\containers\smoke_test.py') --expect $Expect --api "http://${VmPrivateIp}:$port" --through-proxy $Site
exit $LASTEXITCODE
