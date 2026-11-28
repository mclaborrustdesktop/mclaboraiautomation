# Takes the "results" folder that comes back from the live server (Setup-ReadOnlyLogin-OnServer.ps1) and configures the
# office sync agent on THIS PC, as the Windows account that runs the agent:
#   1. decrypts results\mclabor_web_read.password.cms with the transfer key's private key (this account's store only) and
#      stores the password DPAPI in %LOCALAPPDATA%\MCLabor\production-mclabor_web_read.dpapi (the file run-sync.ps1 reads);
#      the password is never displayed, logged or written in clear;
#   2. stores the cloud sync key for the agent (sync-production.dpapi) from the prepared production variables, if missing;
#   3. trusts the server's public certificate (results\<server>-sqlserver.cer) in THIS account's Trusted Root store (Windows
#      asks once, click Yes) or, in an administrator window, in the computer's store - so the agent VERIFIES the server;
#   4. writes tools\sync\sync.env from the prepared production settings (certificate verification ON, no TLS waiver);
#   5. runs the isolated read-only connection check (metadata only) and the agent's dry run (reads, compares, sends nothing).
# Nothing is sent to the website, nothing on the server is changed. Re-runnable.
#   powershell -ExecutionPolicy Bypass -File tools\production\Import-ClientSetupResults.ps1 -Folder "<...>\results"
param([Parameter(Mandatory = $true)][string]$Folder, [switch]$SkipChecks, [string]$Server = '')   # -Server: another host than the live one (rehearsals)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$hosts = @(Get-Content (Join-Path $repo 'backend\office-hosts.txt') | Where-Object { $_ -and -not $_.StartsWith('#') } | ForEach-Object { $_.Trim() })
$live = if ($Server) { $Server } else { $hosts[0] }
if (Test-Path (Join-Path $Folder 'results')) { $Folder = Join-Path $Folder 'results' }
$dir = Join-Path $env:LOCALAPPDATA 'MCLabor'
New-Item -ItemType Directory -Force $dir | Out-Null
function OwnerOnly($path) { icacls $path /inheritance:r | Out-Null; icacls $path /grant:r "${env:USERDOMAIN}\${env:USERNAME}:(R,W)" | Out-Null }

# 1. the password
$cms = Get-ChildItem $Folder -Filter '*.cms' | Select-Object -First 1
$dbFile = Join-Path $dir 'production-mclabor_web_read.dpapi'
if ($cms) {
    $secure = ConvertTo-SecureString -String (Unprotect-CmsMessage -Path $cms.FullName) -AsPlainText -Force
    ConvertFrom-SecureString $secure | Set-Content -Path $dbFile -Encoding ascii
    OwnerOnly $dbFile
    Write-Output "1. Password of mclabor_web_read: decrypted from $($cms.Name) and stored DPAPI for $env:USERDOMAIN\$env:USERNAME -> $dbFile"
} elseif (Test-Path $dbFile) {
    Write-Output "1. No .cms file in $Folder; the already stored password is kept ($dbFile)."
} else {
    Write-Output "1. No .cms file in $Folder and no stored password. If the administrator wrote the password down, run tools\sync\store-sync-secrets.ps1 -Environment production and type it at the hidden prompt."
}

# 2. the sync key for the agent
$syncFile = Join-Path $dir 'sync-production.dpapi'
$vars = Join-Path $dir 'production\backend.production.variables.env'
if (-not (Test-Path $syncFile)) {
    $line = if (Test-Path $vars) { Get-Content $vars | Where-Object { $_ -like 'SYNC_API_KEY=*' } | Select-Object -First 1 } else { $null }
    if ($line) {
        $payload = @{ sync_key = $line.Substring('SYNC_API_KEY='.Length).Trim(); cf_secret = '' } | ConvertTo-Json -Compress
        ConvertTo-SecureString -String $payload -AsPlainText -Force | ConvertFrom-SecureString | Set-Content -Path $syncFile -Encoding ascii
        OwnerOnly $syncFile
        Write-Output "2. Cloud sync key: stored for the agent from the prepared production variables -> $syncFile"
    } else { Write-Output '2. Cloud sync key: not stored (prepared production variables not found); run tools\railway\Build-ProductionVariables.ps1 first.' }
} else { Write-Output "2. Cloud sync key: already stored ($syncFile)." }

# 3. the server certificate
$cer = Get-ChildItem $Folder -Filter '*.cer' | Where-Object { $_.Name -ne 'transfer-key.cer' } | Select-Object -First 1
$trusted = $false
if ($cer) {
    $cert = New-Object Security.Cryptography.X509Certificates.X509Certificate2($cer.FullName)
    if ($cert.HasPrivateKey) { throw 'The .cer file contains a private key; only the public export may be trusted. Stopped.' }
    if (-not ($cert.DnsNameList.Unicode -contains $live) -and $cert.Subject -ne "CN=$live") { throw "The certificate is for '$($cert.Subject)', not for $live. Stopped." }
    if ((Get-Date) -gt $cert.NotAfter) { throw 'The certificate has expired. Stopped.' }
    $already = @(Get-ChildItem Cert:\CurrentUser\Root, Cert:\LocalMachine\Root | Where-Object { $_.Thumbprint -eq $cert.Thumbprint })
    if ($already.Count) { Write-Output "3. Server certificate $($cert.Thumbprint) ($($cert.Subject)) is already trusted on this PC."; $trusted = $true }
    else {
        $elevated = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
        $where = if ($elevated) { 'LocalMachine' } else { 'CurrentUser' }
        if (-not $elevated) { Write-Output "   Windows will ask once whether to install the certificate '$($cert.Subject)' as a trusted root for this account: click Yes." }
        $store = New-Object Security.Cryptography.X509Certificates.X509Store('Root', $where)
        $store.Open('ReadWrite'); $store.Add($cert); $store.Close()
        $trusted = @(Get-ChildItem "Cert:\$where\Root" | Where-Object { $_.Thumbprint -eq $cert.Thumbprint }).Count -gt 0
        Write-Output $(if ($trusted) { "3. Server certificate trusted ($where store): $($cert.Subject), valid to $($cert.NotAfter.ToString('yyyy-MM-dd')), thumbprint $($cert.Thumbprint)" } else { '3. Server certificate NOT trusted (the prompt was declined). The agent will refuse to connect until it is.' })
    }
} else { Write-Output "3. No server certificate in $Folder (the administrator skipped the certificate step). The agent verifies certificates and will not connect until RUN-ME.cmd is run again as administrator for that step." }

# 4. the agent's settings
$envFile = Join-Path $repo 'tools\sync\sync.env'
$prepared = Join-Path $dir 'production\sync.env'
if (-not (Test-Path $envFile)) {
    if (-not (Test-Path $prepared)) { throw "Neither $envFile nor the prepared $prepared exists. Run tools\railway\Build-ProductionVariables.ps1 first." }
    Copy-Item $prepared $envFile
}
$lines = Get-Content $envFile
$lines = $lines | ForEach-Object {
    if ($_ -like 'PRODUCTION_DB_SERVER=*') { "PRODUCTION_DB_SERVER=$live,1433" }          # fixed port: the Browser service does not answer
    elseif ($_ -like 'PRODUCTION_DB_USER=*') { 'PRODUCTION_DB_USER=mclabor_web_read' }
    elseif ($_ -like 'PRODUCTION_DB_ENCRYPT=*') { 'PRODUCTION_DB_ENCRYPT=true' }
    elseif ($_ -like 'PRODUCTION_DB_TRUST_SERVER_CERTIFICATE=*') { 'PRODUCTION_DB_TRUST_SERVER_CERTIFICATE=false' }
    elseif ($_ -like 'PRODUCTION_DB_TLS_WAIVER=*') { '# (no TLS waiver: the server certificate is verified)' }
    else { $_ }
}
[IO.File]::WriteAllText($envFile, (($lines -join "`r`n") + "`r`n"), (New-Object Text.UTF8Encoding $false))
Write-Output "4. Agent settings written: $envFile (server $live,1433, login mclabor_web_read, encryption on, certificate verification on)."

$prodcheck = Join-Path $repo 'tools\prod-check\prodcheck.env.production'
if (-not (Test-Path $prodcheck)) {
    $t = [IO.File]::ReadAllText((Join-Path $repo 'tools\prod-check\prodcheck.env.production.example'), [Text.Encoding]::UTF8).Replace('LIVE-HOST', $live)
    [IO.File]::WriteAllText($prodcheck, $t, (New-Object Text.UTF8Encoding $false))
}

# 5. checks (read-only; nothing sent)
if ($SkipChecks) { Write-Output '5. Checks skipped (-SkipChecks).'; exit 0 }
if (-not (Test-Path $dbFile)) { Write-Output '5. Checks skipped: no stored password yet.'; exit 1 }
if (-not $trusted) { Write-Output '5. Checks skipped: the server certificate is not trusted yet.'; exit 1 }
Write-Output ''; Write-Output '5a. Isolated read-only connection check (metadata only, certificate verified) ...'
& (Join-Path $repo 'tools\prod-check\run-prodcheck-production.ps1'); $c1 = $LASTEXITCODE
Write-Output ''; Write-Output '5b. Sync agent DRY RUN (reads the approved tables, compares, sends nothing) ...'
& (Join-Path $repo 'tools\sync\run-sync.ps1') -DryRun; $c2 = $LASTEXITCODE
Write-Output ''
Write-Output "Result: connection check exit $c1, dry run exit $c2 (0 = passed). Nothing was sent to the website; nothing on the server changed."
exit $(if ($c1 -eq 0 -and $c2 -eq 0) { 0 } else { 1 })
