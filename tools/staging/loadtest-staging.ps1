# Load-tests the website against the STAGING copy WITHOUT touching the DEMO website on port 8000.
#   powershell -ExecutionPolicy Bypass -File tools\staging\loadtest-staging.ps1 -People "35,60" -StaffId 77
# Starts a second backend (staging settings, restricted read-only login, 4 worker processes) on port 8001 through
# run-readonly.ps1, runs tools\staging\loadtest.py once per people-count, then stops that backend again.
# -StaffId is the OfficeStaffID the test signs in as (tools\staging\pilot_identity.py prints a suitable one).
# -Extra sets further environment values for the backend under test, e.g. "MAX_CONCURRENT_SEARCHES=3;SEARCH_WAIT_SECONDS=15".
param(
    [string]$People = '35,60',   # comma-separated people counts, one test each (a string: -File cannot pass arrays)
    [int]$Rounds = 6,
    [Parameter(Mandatory = $true)][int]$StaffId,
    [int]$Port = 8001,
    [string]$Label = '',
    [string]$Extra = '',
    [int]$Workers = 4,           # backend worker processes (a 2-vCPU VM would run 2)
    [int]$AffinityMask = 0       # e.g. 3 = logical processors 0 and 1 only, to approximate a smaller VM; 0 = all
)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$runner = Join-Path $here 'run-readonly.ps1'
$env:WEB_ADMINS = "$StaffId"
foreach ($pair in @($Extra -split ';' | Where-Object { $_ -match '=' })) { $k, $v = $pair.Split('=', 2); [Environment]::SetEnvironmentVariable($k.Trim(), $v.Trim(), 'Process') }
if (Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -eq $Port }) {
    throw "Port $Port is already in use (a previous test backend still running?). Stop it first; nothing was started."
}

function Stop-Tree([int]$ProcessId) {
    # stop a process and everything it spawned (uvicorn's worker processes carry no port in their command line)
    Get-CimInstance Win32_Process -Filter "ParentProcessId = $ProcessId" | ForEach-Object { Stop-Tree $_.ProcessId }
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

$backend = Start-Process -FilePath 'powershell.exe' -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $runner, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', "$Port", '--workers', "$Workers", '--no-access-log' -WindowStyle Hidden -PassThru
function Backend-Processes { Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and ($_.CommandLine -like "*--port $Port*" -or $_.CommandLine -like '*multiprocessing.spawn*') -and $_.CreationDate -gt (Get-Date).AddMinutes(-3) } }
try {
    $ready = $false
    foreach ($i in 1..60) {
        Start-Sleep -Seconds 2
        try { $h = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 5; if ($h.environment -eq 'staging') { $ready = $true; break } } catch {}
    }
    if (-not $ready) { throw "The staging backend on port $Port did not start." }
    if ($AffinityMask) {
        foreach ($p in Backend-Processes) { try { (Get-Process -Id $p.ProcessId).ProcessorAffinity = [IntPtr]$AffinityMask } catch {} }
        Write-Output "Backend processes limited to processor mask $AffinityMask ($Workers worker(s))."
    }
    Write-Output "Staging backend ready on port $Port (environment $($h.environment), parser $($h.ai_mode), $Workers worker(s))."
    foreach ($n in @($People -split ',' | ForEach-Object { [int]$_.Trim() } | Where-Object { $_ -gt 0 })) {
        $lbl = if ($Label) { "$Label-$($n)users" } else { "$($n)users" }
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $runner (Join-Path $here 'loadtest.py') $n $Rounds "http://127.0.0.1:$Port" $lbl
        $mem = (Backend-Processes | ForEach-Object { (Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue).WorkingSet64 } | Measure-Object -Sum).Sum
        Write-Output ("Backend memory after the test: {0:N0} MB across {1} process(es)" -f ($mem / 1MB), (Backend-Processes | Measure-Object).Count)
        Start-Sleep -Seconds 5
    }
}
finally {
    # stop everything that was started for this test: the launcher shell, the uvicorn parent and its worker processes
    if ($backend) { Stop-Tree $backend.Id }
    $left = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -eq $Port }
    foreach ($l in $left) { Stop-Tree $l.OwningProcess }
    Remove-Item Env:\WEB_ADMINS -ErrorAction SilentlyContinue
    Write-Output "Staging backend on port $Port stopped. The DEMO website on port 8000 was not touched."
}
