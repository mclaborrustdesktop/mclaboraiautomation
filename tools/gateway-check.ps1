# READ-ONLY check of this PC before (or after) switching a real-data environment to gateway access.
#   powershell -ExecutionPolicy Bypass -File tools\gateway-check.ps1 [-EnvFile backend\.env.off] [-Probe]
# Looks at: which addresses the website listens on, firewall rules for its ports, the settings file, and the
# browser's API address. -Probe additionally sends two requests to the running backend that must both be refused.
# It changes nothing. Every line is PASS, WARN or FAIL.
param([string]$EnvFile = '', [switch]$Probe)
$ErrorActionPreference = 'Continue'
$root = Resolve-Path (Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) '..')
if (-not $EnvFile) { $EnvFile = Join-Path $root 'backend\.env' }
$fails = 0; $warns = 0
function Pass($m) { Write-Output "  [PASS] $m" }
function Warn($m) { $script:warns++; Write-Output "  [WARN] $m" }
function Fail($m) { $script:fails++; Write-Output "  [FAIL] $m" }

Write-Output "Gateway readiness check - $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
Write-Output "1. Where the website listens (it must be reachable only from this PC)"
foreach ($port in 8000, 3000) {
    $l = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -eq $port }
    if (-not $l) { Warn "Nothing listens on port $port right now (the website is not running, or runs elsewhere)"; continue }
    foreach ($x in $l) {
        if ($x.LocalAddress -in @('127.0.0.1', '::1')) { Pass "Port $port listens on $($x.LocalAddress) only" }
        else { Fail "Port $port listens on $($x.LocalAddress): reachable from the network. Start the backend with --host 127.0.0.1 and the frontend with -H 127.0.0.1" }
    }
}
Write-Output "2. Windows Firewall rules that would open those ports"
$open = Get-NetFirewallPortFilter -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -in @('8000', '3000') } | ForEach-Object { $_ | Get-NetFirewallRule } | Where-Object { $_.Enabled -eq 'True' -and $_.Direction -eq 'Inbound' -and $_.Action -eq 'Allow' }
if ($open) { foreach ($r in $open) { Fail "Inbound allow rule '$($r.DisplayName)' opens port(s) of the website" } } else { Pass 'No inbound allow rule for ports 8000 or 3000' }

Write-Output "3. Settings file $EnvFile"
if (-not (Test-Path $EnvFile)) { Warn 'Settings file not found: the website is in DEMO. Pass -EnvFile backend\.env.off to check the prepared staging settings.' }
else {
    $cfg = @{}
    foreach ($line in Get-Content $EnvFile) { $t = $line.Trim(); if ($t -and -not $t.StartsWith('#') -and $t.Contains('=')) { $k, $v = $t.Split('=', 2); $cfg[$k.Trim()] = $v.Trim() } }
    $env_ = $cfg['DATA_SOURCE']
    if ($env_ -in @('staging', 'production')) { Pass "DATA_SOURCE=$env_" } else { Warn "DATA_SOURCE=$env_ (demo settings: the gateway rules do not apply)" }
    switch ($cfg['ACCESS_MODE']) {
        'gateway' { Pass 'ACCESS_MODE=gateway' }
        'login' { Warn 'ACCESS_MODE=login: the sign-in page is used, not the gateway (fine until the gateway exists)' }
        'open' { Fail 'ACCESS_MODE=open is refused with real data' }
        default { Warn "ACCESS_MODE not set (defaults to login with real data)" }
    }
    $secret = $cfg['GATEWAY_SECRET']
    if ($cfg['ACCESS_MODE'] -eq 'gateway') {
        if ($secret.Length -ge 48) { Pass "GATEWAY_SECRET is $($secret.Length) characters" } elseif ($secret.Length -ge 32) { Warn "GATEWAY_SECRET is only $($secret.Length) characters; 48+ recommended" } else { Fail 'GATEWAY_SECRET missing or shorter than 32 characters' }
        $tp = $cfg['GATEWAY_TRUSTED_PROXIES']; if (-not $tp) { $tp = '127.0.0.1,::1 (default)' }
        Pass "GATEWAY_TRUSTED_PROXIES=$tp"
        if ($cfg['GATEWAY_EMAIL_HEADER']) { Pass "GATEWAY_EMAIL_HEADER=$($cfg['GATEWAY_EMAIL_HEADER'])" } else { Warn 'GATEWAY_EMAIL_HEADER not set: X-Auth-Request-Email (oauth2-proxy) is assumed; Cloudflare Access uses Cf-Access-Authenticated-User-Email' }
    }
    if ($cfg['WEB_ADMINS'] -or $cfg['WEB_USERS']) { Pass "Access lists: WEB_ADMINS=$($cfg['WEB_ADMINS']) WEB_USERS=$($cfg['WEB_USERS'])" } else { Fail 'WEB_ADMINS and WEB_USERS are both empty: nobody can use the website' }
    if ($cfg['ANTHROPIC_API_KEY']) { if ($cfg['CLAUDE_REAL_DATA_APPROVAL']) { Warn 'An outside AI service is enabled with real data (approval recorded)' } else { Fail 'ANTHROPIC_API_KEY is set without CLAUDE_REAL_DATA_APPROVAL: the website will refuse to start' } } else { Pass 'No outside AI service key' }
    if ($cfg['JWT_SECRET'] -and $cfg['JWT_SECRET'].Length -ge 32 -and -not $cfg['JWT_SECRET'].StartsWith('change-me')) { Pass 'JWT_SECRET is set' } else { Fail 'JWT_SECRET missing, short or the demo value' }
    foreach ($k in @("$($env_.ToUpper())_WRITES_ENABLED")) { if ($cfg[$k] -eq 'true') { Fail "$k=true: writes are switched on" } else { Pass "$k is not true (read-only)" } }
}
Write-Output "4. The browser's API address (frontend\.env.local)"
$fe = Join-Path $root 'frontend\.env.local'
$apiUrl = if (Test-Path $fe) { ((Get-Content $fe | Where-Object { $_ -match '^NEXT_PUBLIC_API_URL=' }) -replace '^NEXT_PUBLIC_API_URL=', '').Trim() } else { $null }
if ($apiUrl -match '^https?://(localhost|127\.0\.0\.1)') { Warn "NEXT_PUBLIC_API_URL=$apiUrl works only on this PC. Behind a gateway set it to an empty value so the browser calls /api on the site's own address" }
elseif (-not $apiUrl) { Pass 'NEXT_PUBLIC_API_URL is empty: the browser calls /api on the same address as the site (correct behind a gateway)' }
else { Pass "NEXT_PUBLIC_API_URL=$apiUrl" }

if ($Probe) {
    Write-Output "5. Live probe of the running backend on 127.0.0.1:8000"
    try { $h = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/health' -TimeoutSec 5; Write-Output "         environment=$($h.environment) access_mode=$($h.access_mode)"
        if ($h.access_mode -eq 'open') { Warn 'The running backend is the DEMO (open): the probes below are skipped' }
        else {
            try { Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8000/api/auth/me' -TimeoutSec 5 | Out-Null; Fail 'Anonymous request was answered 200' } catch { if ($_.Exception.Response.StatusCode.value__ -eq 401) { Pass 'Anonymous request refused (401)' } else { Fail "Anonymous request answered $($_.Exception.Response.StatusCode.value__)" } }
            try { Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8000/api/auth/me' -Headers @{ 'X-Auth-Request-Email' = 'someone@example.com'; 'Cf-Access-Authenticated-User-Email' = 'someone@example.com' } -TimeoutSec 5 | Out-Null; Fail 'A forged e-mail header without the secret was accepted' } catch { if ($_.Exception.Response.StatusCode.value__ -in 401, 403) { Pass 'Forged e-mail header without the secret refused' } else { Fail "Forged header answered $($_.Exception.Response.StatusCode.value__)" } }
        }
    } catch { Warn "No backend answers on 127.0.0.1:8000 ($($_.Exception.Message))" }
}
Write-Output ''
Write-Output "RESULT: $fails problem(s), $warns warning(s). Nothing was changed."
exit $(if ($fails) { 1 } else { 0 })
