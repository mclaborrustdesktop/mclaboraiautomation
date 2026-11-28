# Builds the folder the client's administrator runs ONCE on the live server (tools\prod-check\on-server\*), with the
# office names filled in from backend\office-hosts.txt, and the TRANSFER KEY that lets the server hand the new
# read-only password to this PC without anyone reading it:
#   - a document-encryption certificate is created in THIS Windows account's store (Cert:\CurrentUser\My, private key
#     not exportable, no administrator needed) the first time; only its PUBLIC part (transfer-key.cer) goes in the folder;
#   - on the server, Setup-ReadOnlyLogin-OnServer.ps1 encrypts the generated password to that public key (CMS);
#   - back here, Import-ClientSetupResults.ps1 decrypts it with the private key and stores it DPAPI for the sync agent.
# Nothing in the package is secret. Run as the Windows account that will run the sync agent.
#   powershell -ExecutionPolicy Bypass -File tools\production\New-ClientSetupPackage.ps1
param([string]$Out = (Join-Path ([Environment]::GetFolderPath('Desktop')) 'MC Labor - one-time server setup'))
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$hosts = @(Get-Content (Join-Path $repo 'backend\office-hosts.txt') | Where-Object { $_ -and -not $_.StartsWith('#') } | ForEach-Object { $_.Trim() })
$live = $hosts[0]; $devpc = $env:COMPUTERNAME
$src = Join-Path $repo 'tools\prod-check\on-server'
$pins = @{
    '0-live-backup-status.sql'                 = '4e940fe9e7e0e280131ef9dc24f7c1a1ab5821fe8bd7c450ebda8adfa2cfaf9b'
    '4-live-copyonly-backup-with-checksum.sql' = 'a12342e141584eaf6c72db8651a8582e3a8f1b2e2f7b2f6039a620c692261d89'
    'proposed-grants-production.sql'           = '079ec2522372a0c1cfbc1c0c300cc3ed481d2b0d0b4e996221174e6b8d5c9ce4'
    'verify-readonly-login.sql'                = '6b5376d8c086e7f065a2a1e66486431a2d5f1304213f1d6c9e72f7676595af47'
}
function Sha($path) {
    $t = [IO.File]::ReadAllText($path, [Text.Encoding]::UTF8).TrimStart([char]0xFEFF).Replace("`r`n", "`n")
    return [BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($t))).Replace('-', '').ToLower()
}

# the transfer key (reused while valid)
$subject = "CN=MC Labor setup transfer ($devpc)"
$key = Get-ChildItem Cert:\CurrentUser\My | Where-Object { $_.Subject -eq $subject -and $_.NotAfter -gt (Get-Date).AddDays(30) -and $_.HasPrivateKey } | Sort-Object NotAfter -Descending | Select-Object -First 1
if (-not $key) {
    $key = New-SelfSignedCertificate -Type DocumentEncryptionCert -Subject $subject -CertStoreLocation Cert:\CurrentUser\My -KeyExportPolicy NonExportable -KeyLength 2048 -NotAfter (Get-Date).AddYears(2)
    Write-Output "Transfer key created in this account's certificate store (private key not exportable): $($key.Thumbprint)"
} else { Write-Output "Transfer key reused: $($key.Thumbprint) (valid to $($key.NotAfter.ToString('yyyy-MM-dd')))" }

New-Item -ItemType Directory -Force $Out | Out-Null
New-Item -ItemType Directory -Force (Join-Path $Out 'results') | Out-Null
$utf8 = New-Object Text.UTF8Encoding $false
# scripts with the office names filled in
foreach ($f in 'Setup-ReadOnlyLogin-OnServer.ps1', 'RUN-ME.cmd', 'README-for-the-client.txt') {
    $t = [IO.File]::ReadAllText((Join-Path $src $f), [Text.Encoding]::UTF8).Replace('LIVE-HOST', $live).Replace('DEV-PC', $devpc)
    [IO.File]::WriteAllText((Join-Path $Out $f), $t, $utf8)
}
$certScript = [IO.File]::ReadAllText((Join-Path $repo 'tools\prod-check\proposed-certificate-setup-live-host.ps1'), [Text.Encoding]::UTF8).Replace('LIVE-HOST', $live).Replace('DEV-PC', $devpc)
[IO.File]::WriteAllText((Join-Path $Out 'certificate-setup.ps1'), $certScript, $utf8)
# the reviewed SQL files, byte for byte (the setup script checks their hashes)
foreach ($name in $pins.Keys) {
    $p = if ($name -like '*backup*') { Join-Path $repo "tools\prod-check\backup\$name" } else { Join-Path $repo "tools\prod-check\$name" }
    if ((Sha $p) -ne $pins[$name]) { throw "$name differs from the reviewed version; refresh the pinned hash after a review. Package not built." }
    Copy-Item $p (Join-Path $Out $name) -Force
}
Export-Certificate -Cert $key -FilePath (Join-Path $Out 'transfer-key.cer') | Out-Null
Get-ChildItem $Out -Filter 'certificate-setup-state.json' | Remove-Item -ErrorAction SilentlyContinue

$zip = "$Out.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path (Join-Path $Out '*') -DestinationPath $zip
Write-Output ''
Write-Output "Package folder: $Out"
Write-Output "Package zip:    $zip"
Get-ChildItem $Out -File | ForEach-Object { Write-Output ("  {0,-45} {1,8} bytes" -f $_.Name, $_.Length) }
Write-Output ''
Write-Output "For the live server $live. Give the folder (or the zip) to the client's administrator with README-for-the-client.txt."
Write-Output "When the 'results' folder comes back: tools\production\Import-ClientSetupResults.ps1 -Folder <that folder>"
