# Builds the two container images, starts the DEMO stack (synthetic data), runs the smoke test, stops the stack.
#   powershell -ExecutionPolicy Bypass -File tools\containers\run-smoke.ps1 [-KeepRunning]
# Needs Docker Desktop (or Rancher Desktop) running. Uses ports 8001 (backend) and 3001 (frontend) on this PC so the
# DEMO website on 8000/3000 keeps running untouched. Nothing real is involved: the containers seed their own data.
param([switch]$KeepRunning, [int]$ApiPort = 8001, [int]$WebPort = 3001)
$ErrorActionPreference = 'Stop'
$root = Resolve-Path (Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) '..\..')
$compose = Join-Path $root 'deploy\cloud'
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Docker is not installed (tools\docker-readiness.ps1 says what this PC needs). Nothing was run.' }
docker info *> $null; if ($LASTEXITCODE -ne 0) { throw 'Docker is installed but not running. Start Docker Desktop first.' }
$env:DEMO_API_PORT = "$ApiPort"; $env:DEMO_WEB_PORT = "$WebPort"
Push-Location $compose
try {
    Write-Output "1. Building the images and starting the DEMO stack (first build downloads base images: several minutes)"
    docker compose --profile demo up -d --build
    if ($LASTEXITCODE -ne 0) { throw 'docker compose up failed. See the output above.' }
    Write-Output "2. Smoke test"
    & (Join-Path $root 'backend\.venv\Scripts\python.exe') (Join-Path $root 'tools\containers\smoke_test.py') --api "http://127.0.0.1:$ApiPort" --web "http://127.0.0.1:$WebPort" --expect demo
    $result = $LASTEXITCODE
    Write-Output "3. Container health as Docker sees it"
    docker compose --profile demo ps
}
finally {
    if (-not $KeepRunning) { Write-Output "4. Stopping the DEMO stack"; docker compose --profile demo down -v }
    Pop-Location
}
exit $result
