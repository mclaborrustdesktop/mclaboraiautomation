# READ-ONLY network discovery: is there a SQL Server at the suspected live address, and what does it call itself?
#   powershell -ExecutionPolicy Bypass -File tools\prod-check\find-live-server.ps1 [-Target LIVE-HOST] [-Address <its address; default: resolved from the name>]
# Does: name lookups both ways, ping, a TCP connection attempt to port 1433 (closed again at once, no sign-in),
# and the SQL Server Browser question on UDP 1434, which any SQL Server answers with its instance names, versions
# and ports without any sign-in (the same thing Management Studio's "Browse for servers" does). Also lists this PC's
# ODBC data sources and mapped drives. It signs in to nothing and changes nothing.
param([string]$Target = 'LIVE-HOST', [string]$Address = '')
if (-not $Address) {
    try { $Address = ([Net.Dns]::GetHostAddresses($Target) | Where-Object { $_.AddressFamily -eq 'InterNetwork' } | Select-Object -First 1).IPAddressToString } catch { }
    if (-not $Address) { Write-Output "$Target does not resolve from this PC; pass -Address."; exit 1 }
}
$ErrorActionPreference = 'Continue'
Write-Output "Live-server discovery from $env:COMPUTERNAME - $(Get-Date -Format 'yyyy-MM-dd HH:mm')"

Write-Output "1. Names and addresses"
try { $fwd = [Net.Dns]::GetHostAddresses($Target) | ForEach-Object { $_.IPAddressToString }; Write-Output "   $Target -> $($fwd -join ', ')" } catch { Write-Output "   $Target does not resolve to an address from this PC ($($_.Exception.Message))" }
try { $rev = [Net.Dns]::GetHostEntry($Address).HostName; Write-Output "   $Address -> $rev" } catch { Write-Output "   $Address has no name from this PC ($($_.Exception.Message))" }

Write-Output "2. Reachability"
$ping = Test-Connection -ComputerName $Address -Count 2 -Quiet -ErrorAction SilentlyContinue
Write-Output "   ping $Address : $(if ($ping) { 'answers' } else { 'no answer (may be blocked by its firewall; not conclusive)' })"
foreach ($port in 1433) {
    $client = New-Object Net.Sockets.TcpClient
    try { $ar = $client.BeginConnect($Address, $port, $null, $null); $ok = $ar.AsyncWaitHandle.WaitOne(3000) -and $client.Connected }
    catch { $ok = $false }
    finally { $client.Close() }
    Write-Output "   TCP port $port on $Address : $(if ($ok) { 'OPEN (a SQL Server listens there; nothing was sent)' } else { 'closed or filtered' })"
}

Write-Output "3. SQL Server Browser (UDP 1434): instances the server announces"
try {
    $udp = New-Object Net.Sockets.UdpClient
    $udp.Client.ReceiveTimeout = 3000
    [void]$udp.Send([byte[]](0x02), 1, $Address, 1434)
    $ep = New-Object Net.IPEndPoint([Net.IPAddress]::Any, 0)
    $resp = $udp.Receive([ref]$ep)
    $text = [Text.Encoding]::ASCII.GetString($resp, 3, $resp.Length - 3)
    foreach ($inst in ($text -split ';;' | Where-Object { $_ })) {
        $kv = @{}; $parts = $inst -split ';'
        for ($i = 0; $i + 1 -lt $parts.Count; $i += 2) { $kv[$parts[$i]] = $parts[$i + 1] }
        Write-Output "   server name: $($kv['ServerName'])   instance: $($kv['InstanceName'])   version: $($kv['Version'])   tcp port: $(if ($kv['tcp']) { $kv['tcp'] } else { '(not announced)' })"
    }
    $udp.Close()
} catch { Write-Output "   no answer on UDP 1434 ($($_.Exception.Message)). The Browser service may be stopped or blocked; the instance can still exist on a fixed port." }

Write-Output "4. This PC's ODBC data sources and mapped drives (where staff files might point)"
$dsns = Get-OdbcDsn -ErrorAction SilentlyContinue | Where-Object { $_.DriverName -like '*SQL*' }
if ($dsns) { foreach ($d in $dsns) { Write-Output "   DSN $($d.Name) ($($d.DsnType)): server $($d.Attribute.Server), database $($d.Attribute.Database)" } } else { Write-Output '   no SQL Server ODBC data sources defined' }
$maps = Get-SmbMapping -ErrorAction SilentlyContinue
if ($maps) { foreach ($m in $maps) { Write-Output "   drive $($m.LocalPath) -> $($m.RemotePath)" } } else { Write-Output '   no mapped network drives' }

Write-Output ""
Write-Output "What this proves: whether a SQL Server exists at the address and what it calls itself. What it does NOT prove: that office staff use a database on it. For that, run staff-pc-check.ps1 on a staff PC."
