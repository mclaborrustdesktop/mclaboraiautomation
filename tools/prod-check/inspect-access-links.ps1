# READ-ONLY. Which SQL Server and database does an Access file link to?
#   powershell -ExecutionPolicy Bypass -File tools\prod-check\inspect-access-links.ps1 -Path "C:\path\file.accdb" [-Path ...]
#   powershell -ExecutionPolicy Bypass -File tools\prod-check\inspect-access-links.ps1 -Folder "C:\Users\me\Desktop"
# Reads the file as plain bytes (Access is not started, the file is not opened by Access, nothing is written) and
# lists the distinct SERVER= / DATABASE= / DRIVER= combinations found in its ODBC link strings, with how often each
# occurs. Passwords and user names inside the strings are never printed. Old links that Access has not cleaned out
# of the file also appear, so a file can show more than one server: the most frequent one is usually the current.
param([string[]]$Path = @(), [string]$Folder = '')
$ErrorActionPreference = 'Stop'
$files = @($Path)
if ($Folder) { $files += Get-ChildItem -Path $Folder -Recurse -Include *.accdb, *.accde, *.mdb -File -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName } }
if (-not $files) { throw 'Give -Path or -Folder.' }

foreach ($f in $files) {
    if (-not (Test-Path $f)) { Write-Output "$f : not found"; continue }
    $item = Get-Item $f
    Write-Output ""
    Write-Output "$($item.FullName)"
    Write-Output "   size $([math]::Round($item.Length / 1MB)) MB, last changed $($item.LastWriteTime.ToString('yyyy-MM-dd HH:mm'))"
    $bytes = [IO.File]::ReadAllBytes($item.FullName)
    # link strings are stored either as ANSI or as UTF-16; decode both views and search them for ODBC strings
    $texts = @([Text.Encoding]::GetEncoding(1252).GetString($bytes), [Text.Encoding]::Unicode.GetString($bytes))
    $bytes = $null
    $counts = @{}
    foreach ($t in $texts) {
        foreach ($m in [regex]::Matches($t, '(?i)ODBC;[^\x00]{0,400}')) {
            $s = $m.Value
            $server = [regex]::Match($s, '(?i)SERVER=([^;]+)').Groups[1].Value
            $db = [regex]::Match($s, '(?i)DATABASE=([^;]+)').Groups[1].Value
            $drv = [regex]::Match($s, '(?i)DRIVER=\{?([^;}]+)').Groups[1].Value
            $auth = if ($s -match '(?i)Trusted_Connection=Yes') { 'Windows account' } elseif ($s -match '(?i)UID=') { 'SQL login' } else { '?' }
            if (-not $server -and -not $db) { continue }
            $key = "SERVER=$server | DATABASE=$db | DRIVER=$drv | sign-in: $auth"
            $counts[$key] = 1 + $(if ($counts.ContainsKey($key)) { $counts[$key] } else { 0 })
        }
    }
    $texts = $null
    if (-not $counts.Count) { Write-Output '   no ODBC link strings found (not linked to SQL Server, or links stored differently)'; continue }
    foreach ($k in ($counts.Keys | Sort-Object { $counts[$_] } -Descending)) { Write-Output ("   {0,5} x  {1}" -f $counts[$k], $k) }
}
Write-Output ""
Write-Output "Passwords and user names were not printed. Nothing was changed."
