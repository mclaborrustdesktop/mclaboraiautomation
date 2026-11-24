# Starts the MC Labor AI Automation demo (backend + frontend) in two windows.
# Usage: right-click > Run with PowerShell, or from a terminal:  .\start.ps1
$root = $PSScriptRoot
$node = "$env:USERPROFILE\tools\node"
if (Test-Path $node) { $env:Path = "$node;$env:Path" }

# Backend: prepare/seed once, then 4 worker processes (load-tested with 35 concurrent users).
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$root\backend'; .\.venv\Scripts\python.exe -m app.prepare; `$env:SEED_ON_STARTUP='false'; .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 4"
# Both listen on this PC only (127.0.0.1): nothing on the office network can reach them directly.
Start-Process powershell -ArgumentList "-NoExit", "-Command", "`$env:Path = '$node;' + `$env:Path; Set-Location '$root\frontend'; npx next dev -p 3000 -H 127.0.0.1"

Start-Sleep -Seconds 6
Start-Process "http://localhost:3000"
Write-Host "Backend:  http://localhost:8000/docs"
Write-Host "Frontend: http://localhost:3000   (login ADMIN / mclabor2025)"
