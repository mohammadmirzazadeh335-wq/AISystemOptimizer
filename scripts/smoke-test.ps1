#Requires -Version 5.1
<#
.SYNOPSIS
    Machine-level validation for AI System Optimizer on Windows 11 x64.

.DESCRIPTION
    Checks the machine and the delivered artefacts, and reports PASS / FAIL / NOT VERIFIED for every
    item. There is no fourth state and there is no "OK": an item that could not be checked is reported
    as NOT VERIFIED, never as a pass.

    This script reads. It does not modify the system, with one exception: it can start the optimiser
    to measure it, and only when you ask it to with -MeasureOptimizer.

    The script complements the compiled harness (AISystemOptimizer.SmokeTests), which drives the
    application's own code. Run both: this one proves what the machine is, the harness proves what the
    software does on it.

.PARAMETER ExePath
    Path to the built executable. Default: ..\portable\AIOptimizer.exe

.PARAMETER HarnessPath
    Path to the compiled harness DLL. Leave empty to skip it.

.PARAMETER ExpectedSha256
    If supplied, the executable's hash is compared against this value.

.PARAMETER OutDir
    Where to write the report. Default: the current directory.

.PARAMETER MonitorSeconds
    Passed through to the harness: how long it should watch for leaks. Default 60.

.PARAMETER MeasureOptimizer
    Also start the optimiser, measure its memory and CPU, and close it again.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\smoke-test.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\smoke-test.ps1 -ExpectedSha256 3F2A... -MeasureOptimizer
#>
[CmdletBinding()]
param(
    [string]$ExePath,
    [string]$HarnessPath,
    [string]$ExpectedSha256,
    [string]$OutDir = (Get-Location).Path,
    [int]$MonitorSeconds = 60,
    [switch]$MeasureOptimizer
)

$ErrorActionPreference = 'Continue'
$script:Results = New-Object System.Collections.ArrayList
$script:Started = Get-Date

$root = Split-Path -Parent $PSScriptRoot

if (-not $ExePath)     { $ExePath     = Join-Path $root 'portable\AIOptimizer.exe' }
if (-not $HarnessPath) { $HarnessPath = Join-Path $root 'tools\AISystemOptimizer.SmokeTests\bin\Release\net8.0-windows\AISystemOptimizer.SmokeTests.dll' }

function Add-Result {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][ValidateSet('PASS', 'FAIL', 'NOT VERIFIED')][string]$Status,
        [string]$Detail = ''
    )

    $entry = [pscustomobject]@{
        Name   = $Name
        Status = $Status
        Detail = $Detail
    }

    [void]$script:Results.Add($entry)

    $colour = switch ($Status) {
        'PASS'         { 'Green' }
        'FAIL'         { 'Red' }
        'NOT VERIFIED' { 'Yellow' }
        default        { 'Gray' }
    }

    Write-Host ('  [{0,-13}] {1}' -f $Status, $Name) -ForegroundColor $colour

    if ($Detail) {
        Write-Host ('                 {0}' -f $Detail) -ForegroundColor DarkGray
    }
}

function Get-ItemOrNull {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) { return $null }
    if (Test-Path -LiteralPath $Path) { return (Get-Item -LiteralPath $Path) }
    return $null
}

Write-Host ''
Write-Host 'AI System Optimizer - Windows 11 machine validation' -ForegroundColor Cyan
Write-Host '===================================================' -ForegroundColor Cyan
Write-Host ('Computer : {0}' -f $env:COMPUTERNAME)
Write-Host ('Started  : {0}' -f $script:Started.ToString('yyyy-MM-dd HH:mm:ss'))
$identityName = 'unknown'

try {
    $identityName = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
}
catch {
    $identityName = "(could not be read: $($_.Exception.Message))"
}

Write-Host ('User     : {0}' -f $identityName)
Write-Host ''
Write-Host 'Every item is PASS, FAIL or NOT VERIFIED. An item that could not be checked is not a pass.'
Write-Host ''

# ---------------------------------------------------------------- operating system
Write-Host '== Operating system ==' -ForegroundColor Cyan

$osVersion = $null

try {
    $osVersion = Get-CimInstance -ClassName Win32_OperatingSystem -ErrorAction Stop
}
catch {
    Add-Result -Name 'Operating system can be queried' -Status 'FAIL' -Detail $_.Exception.Message
}

if ($osVersion) {
    Add-Result -Name 'Operating system can be queried' -Status 'PASS' -Detail ('{0} {1}' -f $osVersion.Caption, $osVersion.Version)

    $build = [int]$osVersion.BuildNumber
    $product = $osVersion.Caption

    if ($build -ge 22000) {
        Add-Result -Name 'Windows 11 build >= 22000' -Status 'PASS' -Detail ('Build {0} ({1} {2})' -f $build, $product, $osVersion.Version)
    }
    elseif ($build -ge 10240 -and $build -lt 22000) {
        Add-Result -Name 'Windows 11 build >= 22000' -Status 'NOT VERIFIED' -Detail ('Build {0} is Windows 10. The product targets Windows 11; the same checks apply but this is not the validated platform.' -f $build)
    }
    else {
        Add-Result -Name 'Windows 11 build >= 22000' -Status 'FAIL' -Detail ('Build {0} is not Windows 10 or 11.' -f $build)
    }

    try {
        $cv = Get-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion' -ErrorAction Stop
        $detail = '{0} {1}{2} build {3}.{4}' -f $cv.ProductName, $cv.DisplayVersion, $(if ($cv.EditionID) { ' ' + $cv.EditionID } else { '' }), $cv.CurrentBuildNumber, $cv.UBR
        Add-Result -Name 'Windows edition and feature update' -Status 'PASS' -Detail $detail
    }
    catch {
        Add-Result -Name 'Windows edition and feature update' -Status 'NOT VERIFIED' -Detail $_.Exception.Message
    }

    $ramGb = [math]::Round($osVersion.TotalVisibleMemorySize / 1MB, 2)
    $freeGb = [math]::Round($osVersion.FreePhysicalMemory / 1MB, 2)
    $usedPct = [math]::Round((1 - ($osVersion.FreePhysicalMemory / $osVersion.TotalVisibleMemorySize)) * 100, 1)

    Add-Result -Name 'Physical memory' -Status 'PASS' -Detail ('{0} GB total, {1} GB free, {2}% in use (compare with Task Manager)' -f $ramGb, $freeGb, $usedPct)
}

$arch = $env:PROCESSOR_ARCHITECTURE
$osArch = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()

if ($arch -eq 'AMD64') {
    Add-Result -Name 'Architecture is x64' -Status 'PASS' -Detail ('PROCESSOR_ARCHITECTURE={0}, RuntimeInformation={1}, PROCESSOR_ARCHITEW6432={2}' -f $arch, $osArch, $env:PROCESSOR_ARCHITEW6432)
}
elseif ($osArch -eq 'X64') {
    Add-Result -Name 'Architecture is x64' -Status 'PASS' -Detail ('RuntimeInformation reports {0} (PROCESSOR_ARCHITECTURE={1})' -f $osArch, $arch)
}
elseif ([string]::IsNullOrWhiteSpace($arch) -and [string]::IsNullOrWhiteSpace($osArch)) {
    Add-Result -Name 'Architecture is x64' -Status 'NOT VERIFIED' -Detail 'The architecture could not be read on this host.'
}
else {
    Add-Result -Name 'Architecture is x64' -Status 'FAIL' -Detail ('PROCESSOR_ARCHITECTURE={0}, RuntimeInformation={1} - the validated target is x64.' -f $arch, $osArch)
}

# ---------------------------------------------------------------- privileges
Write-Host ''
Write-Host '== Privileges and UAC ==' -ForegroundColor Cyan

$isAdmin = $null

try {
    $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}
catch {
    $isAdmin = $null
}

# A question that could not be answered is not an answer: if the elevation state could not be read,
# this is NOT VERIFIED - reporting it as a pass would be exactly the kind of claim this project forbids.
if ($null -eq $isAdmin) {
    Add-Result -Name 'Elevation state of this session' -Status 'NOT VERIFIED' -Detail 'The elevation state could not be read on this host.'
}
elseif ($isAdmin) {
    Add-Result -Name 'Elevation state of this session' -Status 'PASS' -Detail 'Elevated. Repeat the run unelevated as well: the application must work as a standard user too.'
}
else {
    Add-Result -Name 'Elevation state of this session' -Status 'PASS' -Detail 'Standard user (unelevated) - the intended default.'
}

try {
    $uac = Get-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System' -ErrorAction Stop

    $enableLua = $uac.EnableLUA
    $consent = $uac.ConsentPromptBehaviorAdmin

    if ($enableLua -eq 1 -and $consent -ne 0) {
        Add-Result -Name 'UAC is enabled with a prompt' -Status 'PASS' -Detail ('EnableLUA={0}, ConsentPromptBehaviorAdmin={1} (0 would mean prompting is disabled)' -f $enableLua, $consent)
    }
    elseif ($enableLua -eq 1) {
        Add-Result -Name 'UAC is enabled with a prompt' -Status 'FAIL' -Detail ('EnableLUA=1 but ConsentPromptBehaviorAdmin={0}, which means administrators are elevated silently. The application never does this.' -f $consent)
    }
    else {
        Add-Result -Name 'UAC is enabled with a prompt' -Status 'FAIL' -Detail 'EnableLUA=0: UAC is switched off on this machine.'
    }
}
catch {
    Add-Result -Name 'UAC is enabled with a prompt' -Status 'NOT VERIFIED' -Detail $_.Exception.Message
}

# ---------------------------------------------------------------- security posture
Write-Host ''
Write-Host '== Security posture (read only - the application must never change these) ==' -ForegroundColor Cyan

try {
    $defender = Get-MpComputerStatus -ErrorAction Stop

    if ($defender.RealTimeProtectionEnabled) {
        Add-Result -Name 'Microsoft Defender real-time protection is ON' -Status 'PASS' -Detail ('RealTimeProtectionEnabled={0}, AntivirusEnabled={1}, AMServiceEnabled={2}' -f $defender.RealTimeProtectionEnabled, $defender.AntivirusEnabled, $defender.AMServiceEnabled)
    }
    else {
        Add-Result -Name 'Microsoft Defender real-time protection is ON' -Status 'FAIL' -Detail 'Real-time protection is off. The application must never be the cause of this, and must refuse any action that would turn it off.'
    }
}
catch {
    Add-Result -Name 'Microsoft Defender real-time protection is ON' -Status 'NOT VERIFIED' -Detail ('Get-MpComputerStatus unavailable ({0}). A third-party antivirus may be installed; the application must still refuse to touch it.' -f $_.Exception.Message)
}

try {
    $profiles = Get-NetFirewallProfile -ErrorAction Stop
    $off = $profiles | Where-Object { -not $_.Enabled }

    if ($off) {
        Add-Result -Name 'Windows Firewall is ON for every profile' -Status 'FAIL' -Detail ('Disabled profile(s): {0}' -f (($off.Name) -join ', '))
    }
    else {
        Add-Result -Name 'Windows Firewall is ON for every profile' -Status 'PASS' -Detail (($profiles | ForEach-Object { '{0}={1}' -f $_.Name, $_.Enabled }) -join ', ')
    }
}
catch {
    Add-Result -Name 'Windows Firewall is ON for every profile' -Status 'NOT VERIFIED' -Detail $_.Exception.Message
}

try {
    $wsc = Get-CimInstance -Namespace 'root\SecurityCenter2' -ClassName AntiVirusProduct -ErrorAction Stop
    Add-Result -Name 'Registered security products' -Status 'PASS' -Detail (($wsc | ForEach-Object { $_.displayName }) -join ', ')
}
catch {
    Add-Result -Name 'Registered security products' -Status 'NOT VERIFIED' -Detail $_.Exception.Message
}

# ---------------------------------------------------------------- hardware
Write-Host ''
Write-Host '== Hardware ==' -ForegroundColor Cyan

try {
    $cpu = Get-CimInstance -ClassName Win32_Processor -ErrorAction Stop | Select-Object -First 1
    Add-Result -Name 'CPU' -Status 'PASS' -Detail ('{0}: {1} cores, {2} logical processors, {3} MHz max, {4} MHz current' -f $cpu.Name.Trim(), $cpu.NumberOfCores, $cpu.NumberOfLogicalProcessors, $cpu.MaxClockSpeed, $cpu.CurrentClockSpeed)
}
catch {
    Add-Result -Name 'CPU' -Status 'NOT VERIFIED' -Detail $_.Exception.Message
}

try {
    $gpus = Get-CimInstance -ClassName Win32_VideoController -ErrorAction Stop

    foreach ($gpu in $gpus) {
        $vram = if ($gpu.AdapterRAM -and $gpu.AdapterRAM -gt 0) { '{0:N0} MB' -f ($gpu.AdapterRAM / 1MB) } else { 'not reported' }
        Add-Result -Name ('GPU: {0}' -f $gpu.Name) -Status 'PASS' -Detail ('driver {0} dated {1}, VRAM {2}' -f $gpu.DriverVersion, $gpu.DriverDate, $vram)
    }
}
catch {
    Add-Result -Name 'GPU' -Status 'NOT VERIFIED' -Detail $_.Exception.Message
}

$gpuEngineCategory = $null

try {
    $gpuEngineCategory = [System.Diagnostics.PerformanceCounterCategory]::Exists('GPU Engine')
}
catch {
    $gpuEngineCategory = $null
}

if ($gpuEngineCategory -eq $true) {
    Add-Result -Name 'GPU usage counters ("GPU Engine")' -Status 'PASS' -Detail 'The counter category exists, so the interface can show a measured GPU figure.'
}
elseif ($gpuEngineCategory -eq $false) {
    Add-Result -Name 'GPU usage counters ("GPU Engine")' -Status 'NOT VERIFIED' -Detail 'The counter category does not exist on this machine. The interface must show N/A here; inventing a number would be a defect.'
}
else {
    Add-Result -Name 'GPU usage counters ("GPU Engine")' -Status 'NOT VERIFIED' -Detail 'The counter category could not be queried.'
}

try {
    $zones = Get-CimInstance -Namespace 'root\WMI' -ClassName MSAcpi_ThermalZoneTemperature -ErrorAction Stop

    if ($zones) {
        $temps = $zones | ForEach-Object { [math]::Round(($_.CurrentTemperature / 10) - 273.15, 1) }
        Add-Result -Name 'CPU temperature sensor' -Status 'PASS' -Detail ('Thermal zone reports {0} C. Cross-check this against the temperature the interface shows.' -f (($temps) -join ', '))
    }
    else {
        Add-Result -Name 'CPU temperature sensor' -Status 'NOT VERIFIED' -Detail 'No thermal zone is exposed. The interface must show N/A here.'
    }
}
catch {
    Add-Result -Name 'CPU temperature sensor' -Status 'NOT VERIFIED' -Detail ('No thermal zone is exposed ({0}). The interface must show N/A here - a number would be fabricated.' -f $_.Exception.Message)
}

try {
    $disks = Get-PhysicalDisk -ErrorAction Stop

    foreach ($disk in $disks) {
        $media = switch ($disk.MediaType) {
            'SSD'              { 'SSD' }
            'HDD'              { 'HDD' }
            'SCM'              { 'SCM' }
            default            { 'Unspecified' }
        }

        $bus = switch ([int]$disk.BusType) {
            17      { 'NVMe' }
            11      { 'SATA' }
            7       { 'USB' }
            8       { 'RAID' }
            default { 'BusType ' + [int]$disk.BusType }
        }

        $status = if ($media -eq 'Unspecified') { 'NOT VERIFIED' } else { 'PASS' }

        Add-Result -Name ('Disk: {0}' -f $disk.FriendlyName) -Status $status -Detail ('{0} GB, media {1}, bus {2}, health {3}. The application must never defragment an SSD.' -f [math]::Round($disk.Size / 1GB, 1), $media, $bus, $disk.HealthStatus)
    }
}
catch {
    Add-Result -Name 'Physical disks' -Status 'NOT VERIFIED' -Detail $_.Exception.Message
}

try {
    $volumes = Get-CimInstance -ClassName Win32_LogicalDisk -Filter 'DriveType = 3' -ErrorAction Stop

    foreach ($volume in $volumes) {
        if ($volume.Size -le 0) { continue }

        $freePct = [math]::Round(($volume.FreeSpace / $volume.Size) * 100, 1)

        Add-Result -Name ('Volume {0}' -f $volume.DeviceID) -Status 'PASS' -Detail ('{0} GB free of {1} GB ({2}%)' -f [math]::Round($volume.FreeSpace / 1GB, 1), [math]::Round($volume.Size / 1GB, 1), $freePct)
    }
}
catch {
    Add-Result -Name 'Volumes' -Status 'NOT VERIFIED' -Detail $_.Exception.Message
}

# ---------------------------------------------------------------- artefacts
Write-Host ''
Write-Host '== Delivered artefacts ==' -ForegroundColor Cyan

$exe = Get-ItemOrNull -Path $ExePath

if ($exe) {
    Add-Result -Name 'Portable executable exists' -Status 'PASS' -Detail ('{0} - {1:N0} bytes, modified {2}' -f $exe.FullName, $exe.Length, $exe.LastWriteTime)

    try {
        $hash = (Get-FileHash -LiteralPath $exe.FullName -Algorithm SHA256).Hash

        if ($ExpectedSha256) {
            if ($hash -eq $ExpectedSha256.ToUpperInvariant()) {
                Add-Result -Name 'SHA-256 matches the published value' -Status 'PASS' -Detail $hash
            }
            else {
                Add-Result -Name 'SHA-256 matches the published value' -Status 'FAIL' -Detail ('found {0}, expected {1}' -f $hash, $ExpectedSha256.ToUpperInvariant())
            }
        }
        else {
            Add-Result -Name 'SHA-256 of the executable' -Status 'PASS' -Detail ('{0} - record this next to the build; pass it back with -ExpectedSha256 to compare.' -f $hash)
        }
    }
    catch {
        Add-Result -Name 'SHA-256 of the executable' -Status 'FAIL' -Detail $_.Exception.Message
    }

    try {
        $signature = Get-AuthenticodeSignature -LiteralPath $exe.FullName
        Add-Result -Name 'Executable signature' -Status 'NOT VERIFIED' -Detail ('Signature status: {0}. An unsigned build is expected for a local test build; it means SmartScreen will warn the first time it is run.' -f $signature.Status)
    }
    catch {
        Add-Result -Name 'Executable signature' -Status 'NOT VERIFIED' -Detail $_.Exception.Message
    }
}
else {
    Add-Result -Name 'Portable executable exists' -Status 'FAIL' -Detail ('Not found at {0}. Build it with: dotnet publish src\AISystemOptimizer.App -c Release -r win-x64 --self-contained true' -f $ExePath)
}

# The self-contained claim can only be proved on a machine without the .NET Runtime, which this
# machine is not. Stating it as verified here would be a fake pass.
$dotnet = Get-Command dotnet -ErrorAction SilentlyContinue
$dotnetInstall = $null

if (-not $dotnet) {
    $machineDotnet = Join-Path $env:ProgramFiles 'dotnet\dotnet.exe'

    if (Test-Path -LiteralPath $machineDotnet) {
        $dotnetInstall = $machineDotnet
    }
}

if ($dotnet -or $dotnetInstall) {
    $found = if ($dotnet) { $dotnet.Source } else { $dotnetInstall }
    $version = 'unknown'

    if ($dotnet) {
        try { $version = (& dotnet --version) 2>$null } catch { }
    }

    Add-Result -Name 'Runtime installed on this machine' -Status 'NOT VERIFIED' -Detail ('A .NET runtime is present (version {0}, {1}). The self-contained claim - "runs on a machine with no .NET Runtime" - cannot be proven on a machine that has one. Use a clean Windows 11 VM with no .NET installed.' -f $version, $found)
}
else {
    Add-Result -Name 'Runtime installed on this machine' -Status 'PASS' -Detail 'No dotnet runtime found on PATH - this machine is a valid test bed for the self-contained build.'
}

# ---------------------------------------------------------------- configuration and logs
Write-Host ''
Write-Host '== Configuration and logs ==' -ForegroundColor Cyan

$configCandidates = New-Object System.Collections.ArrayList

if ($env:LOCALAPPDATA) {
    [void]$configCandidates.Add((Join-Path $env:LOCALAPPDATA 'AISystemOptimizer\config.json'))
}

if ($exe) {
    [void]$configCandidates.Add((Join-Path (Split-Path -Parent $exe.FullName) 'AISystemOptimizerData\config.json'))
}

[void]$configCandidates.Add((Join-Path $root 'config\config.json'))

$configPath = $null

foreach ($candidate in $configCandidates) {
    if (Test-Path -LiteralPath $candidate) {
        $configPath = $candidate
        break
    }
}

if ($configPath) {
    try {
        $config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json

        $problems = New-Object System.Collections.ArrayList

        if ($config.safetyLayerEnabled -eq $false) { [void]$problems.Add('safetyLayerEnabled is false') }
        if ($config.allowHighRiskActions -eq $true) { [void]$problems.Add('allowHighRiskActions is true') }
        if ($config.allowCriticalRiskActions -eq $true) { [void]$problems.Add('allowCriticalRiskActions is true') }
        if ($config.allowRemoteAiServer -eq $true) { [void]$problems.Add('allowRemoteAiServer is true') }
        if ($config.targetRamUsage -gt 90) { [void]$problems.Add('targetRamUsage is out of range') }

        if ($problems.Count -gt 0) {
            Add-Result -Name 'Configuration is safe' -Status 'FAIL' -Detail ('{0}: {1}' -f $configPath, (($problems) -join '; '))
        }
        else {
            Add-Result -Name 'Configuration is safe' -Status 'PASS' -Detail ('{0}: safetyLayerEnabled={1}, maxAutoRiskLevel={2}, targetRamUsage={3}%, aiEnabled={4}, allowRemoteAiServer={5}' -f $configPath, $config.safetyLayerEnabled, $config.maxAutoRiskLevel, $config.targetRamUsage, $config.aiEnabled, $config.allowRemoteAiServer)
        }

        $backup = "$configPath.bak"

        if (Test-Path -LiteralPath $backup) {
            Add-Result -Name 'Configuration backup exists' -Status 'PASS' -Detail $backup
        }
        else {
            Add-Result -Name 'Configuration backup exists' -Status 'NOT VERIFIED' -Detail ('No {0} yet. It appears after the first save.' -f $backup)
        }
    }
    catch {
        Add-Result -Name 'Configuration is safe' -Status 'FAIL' -Detail ('{0} could not be parsed: {1}' -f $configPath, $_.Exception.Message)
    }
}
else {
    Add-Result -Name 'Configuration is safe' -Status 'NOT VERIFIED' -Detail ('No configuration file yet. Searched: {0}. It is created on first save.' -f ($configCandidates -join '; '))
}

$logDirs = New-Object System.Collections.ArrayList

if ($env:LOCALAPPDATA) {
    [void]$logDirs.Add((Join-Path $env:LOCALAPPDATA 'AISystemOptimizer\Logs'))
}

if ($exe) {
    [void]$logDirs.Add((Join-Path (Split-Path -Parent $exe.FullName) 'AISystemOptimizerData\Logs'))
}

[void]$logDirs.Add((Join-Path $root 'Logs'))

$logDir = $null

foreach ($candidate in $logDirs) {
    if (Test-Path -LiteralPath $candidate) {
        $logDir = $candidate
        break
    }
}

if ($logDir) {
    $logFiles = Get-ChildItem -LiteralPath $logDir -Filter '*.log' -ErrorAction SilentlyContinue
    $newest = $logFiles | Sort-Object LastWriteTime -Descending | Select-Object -First 1

    if ($newest) {
        $tail = Get-Content -LiteralPath $newest.FullName -Tail 200 -ErrorAction SilentlyContinue
        $hasTimestamp = ($tail | Where-Object { $_ -match '\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}' } | Measure-Object).Count
        $secretLike = ($tail | Where-Object { $_ -match '(?i)(password|token|api[_ ]?key)\s*[:=]' } | Measure-Object).Count

        if ($secretLike -gt 0) {
            Add-Result -Name 'Logs present and free of secrets' -Status 'FAIL' -Detail ('{0} line(s) in {1} look like a credential.' -f $secretLike, $newest.Name)
        }
        else {
            Add-Result -Name 'Logs present and free of secrets' -Status 'PASS' -Detail ('{0}: {1:N0} bytes, last written {2}, {3} of the last {4} lines carry a timestamp, no credential-like fields' -f $newest.FullName, $newest.Length, $newest.LastWriteTime, $hasTimestamp, $tail.Count)
        }
    }
    else {
        Add-Result -Name 'Logs present and free of secrets' -Status 'NOT VERIFIED' -Detail ('{0} exists but holds no .log file yet.' -f $logDir)
    }
}
else {
    Add-Result -Name 'Logs present and free of secrets' -Status 'NOT VERIFIED' -Detail ('No log directory yet. Searched: {0}. Run the optimiser once.' -f ($logDirs -join '; '))
}

# ---------------------------------------------------------------- the running optimiser
Write-Host ''
Write-Host '== The optimiser while it runs ==' -ForegroundColor Cyan

$processName = [System.IO.Path]::GetFileNameWithoutExtension($ExePath)

function Measure-OptimizerProcess {
    param([string]$Name)

    $process = Get-Process -Name $Name -ErrorAction SilentlyContinue | Select-Object -First 1

    if (-not $process) { return $null }

    $cpuBefore = $process.TotalProcessorTime
    Start-Sleep -Seconds 3
    $process.Refresh()
    $cpuAfter = $process.TotalProcessorTime

    return [pscustomobject]@{
        Id          = $process.Id
        WorkingSet  = [math]::Round($process.WorkingSet64 / 1MB, 1)
        Private     = [math]::Round($process.PrivateMemorySize64 / 1MB, 1)
        Handles     = $process.HandleCount
        Threads     = $process.Threads.Count
        CpuPercent  = [math]::Round((($cpuAfter - $cpuBefore).TotalMilliseconds / 3000) / [Environment]::ProcessorCount * 100, 2)
    }
}

$running = Measure-OptimizerProcess -Name $processName

if ($running) {
    # Already running: measure it without starting anything.
    $status = if ($running.WorkingSet -le 200 -and $running.CpuPercent -lt 5) { 'PASS' } else { 'FAIL' }
    Add-Result -Name 'Optimiser resource use (running copy)' -Status $status -Detail ('pid {0}: working set {1} MB, private {2} MB, handles {3}, threads {4}, CPU {5}% while idle' -f $running.Id, $running.WorkingSet, $running.Private, $running.Handles, $running.Threads, $running.CpuPercent)
}
elseif ($MeasureOptimizer -and $exe) {
    Write-Host '  Starting the optimiser to measure it...' -ForegroundColor DarkGray

    try {
        $started = Start-Process -FilePath $exe.FullName -PassThru
        Start-Sleep -Seconds 12

        $measured = Measure-OptimizerProcess -Name $processName

        if ($measured) {
            $status = if ($measured.WorkingSet -le 200 -and $measured.CpuPercent -lt 5) { 'PASS' } else { 'FAIL' }
            Add-Result -Name 'Optimiser resource use (freshly started)' -Status $status -Detail ('pid {0}: working set {1} MB, private {2} MB, handles {3}, threads {4}, CPU {5}% while idle' -f $measured.Id, $measured.WorkingSet, $measured.Private, $measured.Handles, $measured.Threads, $measured.CpuPercent)
        }
        else {
            Add-Result -Name 'Optimiser resource use (freshly started)' -Status 'FAIL' -Detail ('The process was started but no process named {0} could be measured.' -f $processName)
        }

        Add-Result -Name 'Window opens and closes normally' -Status 'NOT VERIFIED' -Detail 'This script cannot judge the window. Confirm by hand: the window opens, WM_CLOSE closes it, the tray icon behaves, and no dialog appears behind the main window.'

        if ($started -and -not $started.HasExited) {
            $started.CloseMainWindow() | Out-Null
            Start-Sleep -Seconds 3

            if (-not $started.HasExited) {
                Add-Result -Name 'Closing the window ends the process' -Status 'FAIL' -Detail 'The main window was closed but the process is still running.'
                Stop-Process -Id $started.Id -ErrorAction SilentlyContinue
            }
            else {
                Add-Result -Name 'Closing the window ends the process' -Status 'PASS' -Detail 'The process exited after WM_CLOSE.'
            }
        }
    }
    catch {
        Add-Result -Name 'Optimiser resource use (freshly started)' -Status 'FAIL' -Detail $_.Exception.Message
    }
}
else {
    Add-Result -Name 'Optimiser resource use' -Status 'NOT VERIFIED' -Detail ('The optimiser is not running. Start it (or re-run with -MeasureOptimizer) and watch working set, handles and threads in Task Manager for 30 minutes. The budget is under ~100 MB and near 0% CPU when idle.')
}

Add-Result -Name 'Background growth over 30 minutes' -Status 'NOT VERIFIED' -Detail 'Requires a real 30-minute observation of the running application. The harness measures 60 seconds of it (-MonitorSeconds); the long run must be done by hand.'

# ---------------------------------------------------------------- compiled harness
Write-Host ''
Write-Host '== Compiled harness (drives the application code) ==' -ForegroundColor Cyan

$harness = Get-ItemOrNull -Path $HarnessPath

if (-not $harness) {
    Add-Result -Name 'Harness results' -Status 'NOT VERIFIED' -Detail ('Harness not found at {0}. Build it with: dotnet build tools\AISystemOptimizer.SmokeTests -c Release' -f $HarnessPath)
}
elseif (-not $dotnet) {
    Add-Result -Name 'Harness results' -Status 'NOT VERIFIED' -Detail 'No dotnet runtime is on PATH, so the harness could not be launched.'
}
else {
    $harnessReport = Join-Path $OutDir 'harness-results.md'

    Write-Host ('  Running {0} --monitor-seconds {1} ...' -f $harness.FullName, $MonitorSeconds) -ForegroundColor DarkGray

    $harnessOutput = & dotnet $harness.FullName --output $harnessReport --monitor-seconds $MonitorSeconds 2>&1
    $harnessExit = $LASTEXITCODE

    $summary = ($harnessOutput | Where-Object { $_ -match 'PASS \d+\s+FAIL \d+\s+NOT VERIFIED \d+' } | Select-Object -Last 1)

    if ($harnessExit -eq 0) {
        Add-Result -Name 'Harness results' -Status 'PASS' -Detail ('{0} (report: {1})' -f $summary, $harnessReport)
    }
    elseif ($harnessExit -gt 0) {
        $failures = ($harnessOutput | Where-Object { $_ -match '^\s{4}C\d{3}' }) -join ' | '
        Add-Result -Name 'Harness results' -Status 'FAIL' -Detail ('{0} - failed checks: {1} (report: {2})' -f $summary, $failures, $harnessReport)
    }
    else {
        Add-Result -Name 'Harness results' -Status 'FAIL' -Detail ('The harness could not run (exit {0}): {1}' -f $harnessExit, ($harnessOutput -join ' '))
    }
}

# ---------------------------------------------------------------- things only a person can judge
Write-Host ''
Write-Host '== Checks this script cannot make ==' -ForegroundColor Cyan

Add-Result -Name 'Runtime behaviour requiring a person' -Status 'NOT VERIFIED' -Detail 'Dark and light theme readability, RTL and font fallback, keyboard navigation and focus order, every button doing something, the optimisation preview reading correctly, and whether the interface froze during a scan. Follow docs/SMOKE_TEST.md.'
Add-Result -Name 'Real optimisation end to end' -Status 'NOT VERIFIED' -Detail 'Run one real optimisation on this machine: the before/after report must match Task Manager, the numbers must be percentage points rather than invented percentages, Undo must put everything back, and the startup entry must return exactly as it was.'

# ---------------------------------------------------------------- report
$finished = Get-Date
$passCount = ($script:Results | Where-Object { $_.Status -eq 'PASS' }).Count
$failCount = ($script:Results | Where-Object { $_.Status -eq 'FAIL' }).Count
$notVerifiedCount = ($script:Results | Where-Object { $_.Status -eq 'NOT VERIFIED' }).Count

Write-Host ''
Write-Host '------------------------------------------------------------------------------' -ForegroundColor Cyan
Write-Host ('  PASS {0}   FAIL {1}   NOT VERIFIED {2}   ({3:N0}s)' -f $passCount, $failCount, $notVerifiedCount, ($finished - $script:Started).TotalSeconds) -ForegroundColor Cyan
Write-Host '------------------------------------------------------------------------------' -ForegroundColor Cyan

if ($failCount -gt 0) {
    Write-Host ''
    Write-Host '  Failures:' -ForegroundColor Red
    $script:Results | Where-Object { $_.Status -eq 'FAIL' } | ForEach-Object { Write-Host ('    {0}' -f $_.Name) -ForegroundColor Red }
}

Write-Host ''
Write-Host '  A NOT VERIFIED item is not a pass. List it in the report as not validated, with the reason.' -ForegroundColor Yellow

if (-not (Test-Path -LiteralPath $OutDir)) {
    New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
}

$reportPath = Join-Path $OutDir ('windows-smoke-test-{0:yyyyMMdd-HHmmss}.md' -f $finished)

$report = New-Object System.Collections.ArrayList
[void]$report.Add('# Windows machine validation')
[void]$report.Add('')
[void]$report.Add(('- Machine: {0}' -f $env:COMPUTERNAME))
[void]$report.Add(('- Run at: {0}' -f $finished.ToString('yyyy-MM-dd HH:mm:ss zzz')))
[void]$report.Add(('- Elevated: {0}' -f $isAdmin))
[void]$report.Add(('- Executable: {0}' -f $(if ($exe) { $exe.FullName } else { 'not found' })))
[void]$report.Add(('- Harness: {0}' -f $(if ($harness) { $harness.FullName } else { 'not found' })))
[void]$report.Add('')
[void]$report.Add(('**PASS {0} · FAIL {1} · NOT VERIFIED {2}**' -f $passCount, $failCount, $notVerifiedCount))
[void]$report.Add('')
[void]$report.Add('| Status | Check | Detail |')
[void]$report.Add('|---|---|---|')

foreach ($entry in $script:Results) {
    $detail = ($entry.Detail -replace '\|', '\|') -replace "`r?`n", ' '
    [void]$report.Add(('| {0} | {1} | {2} |' -f $entry.Status, $entry.Name, $detail))
}

$report | Set-Content -LiteralPath $reportPath -Encoding UTF8

Write-Host ''
Write-Host ('  Report: {0}' -f $reportPath) -ForegroundColor Cyan
Write-Host ''

# The exit code is the number of failures, so a build pipeline can gate on it.
exit $failCount
