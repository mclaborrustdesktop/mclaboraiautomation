# Run ON THE VM as administrator, once. Installs what the website needs, from the vendors' own download links,
# pinned to versions that are known to work with this code. Nothing else on the VM is changed.
#   powershell -ExecutionPolicy Bypass -File install-prerequisites.ps1 [-Plan]
# -Plan prints what would be downloaded and installed without doing it.
#Requires -RunAsAdministrator
param([switch]$Plan, [string]$Root = 'C:\mclabor')
$ErrorActionPreference = 'Stop'
$dl = Join-Path $Root 'downloads'
$tools = Join-Path $Root 'tools'
$items = @(
    @{ Name = 'Python 3.12';             Url = 'https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe'; File = 'python-3.12.8-amd64.exe'
       Install = { & "$dl\python-3.12.8-amd64.exe" /quiet InstallAllUsers=1 PrependPath=1 Include_test=0 | Out-Null }; Check = { Get-Command py -ErrorAction SilentlyContinue } },
    @{ Name = 'Node.js 22 LTS';          Url = 'https://nodejs.org/dist/v22.12.0/node-v22.12.0-x64.msi'; File = 'node-v22.12.0-x64.msi'
       Install = { Start-Process msiexec.exe -ArgumentList "/i `"$dl\node-v22.12.0-x64.msi`" /qn" -Wait }; Check = { Get-Command node -ErrorAction SilentlyContinue } },
    @{ Name = 'ODBC Driver 18 for SQL Server'; Url = 'https://go.microsoft.com/fwlink/?linkid=2249006'; File = 'msodbcsql18.msi'
       Install = { Start-Process msiexec.exe -ArgumentList "/i `"$dl\msodbcsql18.msi`" /qn IACCEPTMSODBCSQLLICENSETERMS=YES" -Wait }; Check = { Get-OdbcDriver -Name 'ODBC Driver 18 for SQL Server' -ErrorAction SilentlyContinue } },
    @{ Name = 'SqlCmd (for backups)';     Url = 'https://go.microsoft.com/fwlink/?linkid=2230791'; File = 'MsSqlCmdLnUtils.msi'
       Install = { Start-Process msiexec.exe -ArgumentList "/i `"$dl\MsSqlCmdLnUtils.msi`" /qn IACCEPTMSSQLCMDLNUTILSLICENSETERMS=YES" -Wait }; Check = { Get-Command sqlcmd -ErrorAction SilentlyContinue } },
    @{ Name = 'NSSM 2.24 (service wrapper)'; Url = 'https://nssm.cc/release/nssm-2.24.zip'; File = 'nssm-2.24.zip'
       Install = { Expand-Archive "$dl\nssm-2.24.zip" -DestinationPath $dl -Force; Copy-Item "$dl\nssm-2.24\win64\nssm.exe" "$tools\nssm.exe" -Force }; Check = { Test-Path "$tools\nssm.exe" } },
    @{ Name = 'cloudflared (tunnel)';     Url = 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe'; File = 'cloudflared.exe'
       Install = { Copy-Item "$dl\cloudflared.exe" "$tools\cloudflared.exe" -Force }; Check = { Test-Path "$tools\cloudflared.exe" } },
    @{ Name = 'AzCopy (backup upload)';   Url = 'https://aka.ms/downloadazcopy-v10-windows'; File = 'azcopy.zip'
       Install = { Expand-Archive "$dl\azcopy.zip" -DestinationPath $dl -Force; Copy-Item (Get-ChildItem $dl -Recurse -Filter azcopy.exe | Select-Object -First 1).FullName "$tools\azcopy.exe" -Force }; Check = { Test-Path "$tools\azcopy.exe" } }
)
foreach ($d in $Root, $dl, $tools, "$Root\logs") { if (-not (Test-Path $d)) { if ($Plan) { Write-Output "would create $d" } else { New-Item -ItemType Directory -Force $d | Out-Null } } }
foreach ($it in $items) {
    if (& $it.Check) { Write-Output "[present] $($it.Name)"; continue }
    if ($Plan) { Write-Output "[plan]    $($it.Name): download $($it.Url) -> $dl\$($it.File), then install"; continue }
    Write-Output "[install] $($it.Name)"
    Invoke-WebRequest -Uri $it.Url -OutFile (Join-Path $dl $it.File) -UseBasicParsing
    & $it.Install
    if (-not (& $it.Check)) { throw "$($it.Name) did not install. Stopped." }
}
if (-not $Plan) {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    Write-Output "Python: $(& py -3.12 --version)   Node: $(& node --version)   cloudflared: $(& "$tools\cloudflared.exe" --version)"
    Write-Output "Done. Next: deploy-app.ps1 (SETUP.md step 5)."
}
