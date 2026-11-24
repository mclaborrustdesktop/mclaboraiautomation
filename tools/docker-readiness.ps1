# READ-ONLY: can this PC run Docker Desktop (or Rancher Desktop) for building and testing the container images?
#   powershell -ExecutionPolicy Bypass -File tools\docker-readiness.ps1
# Looks at the Windows edition, memory, disk, CPU virtualization, the Hyper-V / WSL features and whether Docker is
# already present. Installs nothing and changes nothing.
$ErrorActionPreference = 'Continue'
$fails = 0; $warns = 0
function Pass($m) { Write-Output "  [PASS] $m" }
function Warn($m) { $script:warns++; Write-Output "  [WARN] $m" }
function Fail($m) { $script:fails++; Write-Output "  [FAIL] $m" }
Write-Output "Docker readiness of $env:COMPUTERNAME - $(Get-Date -Format 'yyyy-MM-dd HH:mm')"

$os = Get-CimInstance Win32_OperatingSystem
$build = [int]$os.BuildNumber
if ($os.Caption -match 'Pro|Enterprise|Education') { Pass "$($os.Caption) build $build (Hyper-V and WSL 2 available)" } elseif ($os.Caption -match 'Home') { Warn "$($os.Caption): WSL 2 works, Hyper-V does not; Docker Desktop uses WSL 2" } else { Warn "$($os.Caption)" }
if ($build -ge 19041) { Pass 'Build is new enough for WSL 2' } else { Fail 'Windows build older than 19041: WSL 2 not supported' }
$ramGb = [math]::Round($os.TotalVisibleMemorySize / 1MB, 1)
if ($ramGb -ge 16) { Pass "$ramGb GB memory (Docker Desktop reserves 2-8 GB; the website stack needs about 2 GB)" } elseif ($ramGb -ge 8) { Warn "$ramGb GB memory: workable, tight next to SQL Server" } else { Fail "$ramGb GB memory: too little" }
$free = [math]::Round((Get-PSDrive C).Free / 1GB)
if ($free -ge 40) { Pass "$free GB free on C: (images and build cache need 10-20 GB)" } else { Warn "$free GB free on C:" }
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
$cs = Get-CimInstance Win32_ComputerSystem
if ($cs.HypervisorPresent) { Pass "A hypervisor is already running (Hyper-V / virtualization-based security): CPU virtualization is enabled" }
elseif ($cpu.VirtualizationFirmwareEnabled) { Pass 'CPU virtualization is enabled in firmware' }
else { Fail 'CPU virtualization appears disabled in the firmware (BIOS/UEFI setting "Intel VT-x / AMD-V"); Docker cannot run until it is enabled' }
Pass "$($cpu.Name.Trim()), $($cpu.NumberOfCores) cores / $($cpu.NumberOfLogicalProcessors) threads"

$elevated = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if ($elevated) {
    foreach ($name in 'Microsoft-Windows-Subsystem-Linux', 'VirtualMachinePlatform', 'Microsoft-Hyper-V-All', 'Containers') {
        $f = Get-WindowsOptionalFeature -Online -FeatureName $name -ErrorAction SilentlyContinue
        if ($f) { Write-Output "         feature $name : $($f.State)" }
    }
} else { Write-Output '         (run as administrator to list the Windows features WSL / Hyper-V / Containers)' }
$wslOut = & wsl.exe --status 2>&1 | Out-String
if ($LASTEXITCODE -eq 0 -and $wslOut -notmatch 'not installed') { Pass 'WSL 2 is installed' } else { Warn 'WSL 2 is not installed. Docker Desktop installs it (one reboot), or run "wsl --install" first (administrator)' }
if (Get-Command docker -ErrorAction SilentlyContinue) { Pass "Docker is already installed: $(docker --version)" } else { Warn 'Docker is not installed' }
$sql = Get-Service 'MSSQL$SQLEXPRESS' -ErrorAction SilentlyContinue
if ($sql) { Warn "SQL Server Express ($($sql.Status)) runs on this PC with the restored copy of real data: Docker Desktop does not touch it, but the install reboots the PC once" }
Write-Output ''
Write-Output 'Licensing: Docker Desktop is free for companies with fewer than 250 employees AND under 10 million USD revenue; otherwise a paid subscription or the free Rancher Desktop (also WSL 2) is the choice.'
Write-Output "RESULT: $fails problem(s), $warns warning(s). Nothing was installed or changed."
exit $(if ($fails) { 1 } else { 0 })
