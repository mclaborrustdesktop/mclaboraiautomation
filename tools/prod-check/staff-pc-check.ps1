# READ-ONLY, for a STAFF PC. Which Access file does this person use, and which SQL Server and database does it use?
#   Copy this one file to the staff PC (USB stick or e-mail), then in PowerShell:
#   powershell -ExecutionPolicy Bypass -File staff-pc-check.ps1 > result.txt
#   and send result.txt back. It contains no password and no data from the database.
# It looks for Access shortcuts on the Desktop, in the Start menu and in "Recent", follows them to the files, and
# reads each file as plain bytes for its SQL Server link strings (SERVER= and DATABASE= only). Access is not started
# and nothing is written. Takes about a minute.
$ErrorActionPreference = 'Continue'
Write-Output "Staff PC check - $env:COMPUTERNAME, user $env:USERNAME - $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
$shell = New-Object -ComObject WScript.Shell
$places = @("$env:USERPROFILE\Desktop", "$env:PUBLIC\Desktop", "$env:APPDATA\Microsoft\Windows\Start Menu", "$env:ProgramData\Microsoft\Windows\Start Menu", "$env:APPDATA\Microsoft\Windows\Recent", "$env:APPDATA\Microsoft\Office\Recent")
$targets = @{}
foreach ($p in $places) {
    if (-not (Test-Path $p)) { continue }
    foreach ($lnk in Get-ChildItem $p -Recurse -Filter *.lnk -ErrorAction SilentlyContinue) {
        try { $t = $shell.CreateShortcut($lnk.FullName).TargetPath } catch { continue }
        if ($t -match '\.(accdb|accde|mdb)$' -or $t -match 'MSACCESS') {
            $args_ = $shell.CreateShortcut($lnk.FullName).Arguments
            $file = if ($t -match '\.(accdb|accde|mdb)$') { $t } elseif ($args_ -match '"?([^"]+\.(accdb|accde|mdb))"?') { $Matches[1] } else { $null }
            if ($file) { $targets[$file] = "$($lnk.FullName) (shortcut changed $($lnk.LastWriteTime.ToString('yyyy-MM-dd')))" }
        }
    }
}
foreach ($p in @("$env:USERPROFILE\Desktop", "$env:USERPROFILE\Documents")) {
    foreach ($f in Get-ChildItem $p -Include *.accdb, *.accde, *.mdb -Recurse -File -ErrorAction SilentlyContinue) { if (-not $targets.ContainsKey($f.FullName)) { $targets[$f.FullName] = 'found in a folder' } }
}
if (-not $targets.Count) { Write-Output 'No Access files or shortcuts found for this user. Ask the person which file they open and run again with that path as -Path on inspect-access-links.ps1.' }
foreach ($file in $targets.Keys) {
    Write-Output ""
    Write-Output "$file"
    Write-Output "   via: $($targets[$file])"
    if (-not (Test-Path $file)) { Write-Output '   file not reachable from this PC right now (network drive?)'; continue }
    $item = Get-Item $file
    Write-Output "   size $([math]::Round($item.Length / 1MB)) MB, last changed $($item.LastWriteTime.ToString('yyyy-MM-dd HH:mm'))"
    try { $bytes = [IO.File]::ReadAllBytes($file) } catch { Write-Output "   cannot read ($($_.Exception.Message))"; continue }
    $counts = @{}
    foreach ($t in @([Text.Encoding]::GetEncoding(1252).GetString($bytes), [Text.Encoding]::Unicode.GetString($bytes))) {
        foreach ($m in [regex]::Matches($t, '(?i)ODBC;[^\x00]{0,400}')) {
            $server = [regex]::Match($m.Value, '(?i)SERVER=([^;]+)').Groups[1].Value
            $db = [regex]::Match($m.Value, '(?i)DATABASE=([^;]+)').Groups[1].Value
            if (-not $server -and -not $db) { continue }
            $key = "SERVER=$server | DATABASE=$db"
            $counts[$key] = 1 + $(if ($counts.ContainsKey($key)) { $counts[$key] } else { 0 })
        }
    }
    $bytes = $null
    if (-not $counts.Count) { Write-Output '   no SQL Server links found in this file' }
    foreach ($k in ($counts.Keys | Sort-Object { $counts[$_] } -Descending)) { Write-Output ("   {0,5} x  {1}" -f $counts[$k], $k) }
}
Write-Output ""
Write-Output "Done. The most frequent SERVER/DATABASE of the file this person really opens is the live database. No password was read or printed."
