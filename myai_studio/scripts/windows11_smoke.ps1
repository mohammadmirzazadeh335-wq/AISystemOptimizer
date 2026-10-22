#requires -Version 5.1
<#
.SYNOPSIS
    One-command Windows 11 verification for MyAI Studio Ultimate.

.DESCRIPTION
    Creates a virtual environment, installs the pinned dependencies, runs the
    portability check, runs the full test suite, then starts the real window with
    --smoke so the GUI is actually constructed and torn down.

    Every step prints PASS / FAIL. The script stops at the first failure and
    exits non-zero, so the output can be attached to a report without editing.

.PARAMETER Python
    Interpreter to build the venv with. Default: "py -3.11" when available.

.PARAMETER SkipTests
    Skip the pytest step (only run the portability check and the GUI smoke test).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\windows11_smoke.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\windows11_smoke.ps1 -Python "C:\Python311\python.exe"
#>
[CmdletBinding()]
param(
    [string]$Python = "",
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$failures = 0

function Step([string]$Name) {
    Write-Host ""
    Write-Host "== $Name" -ForegroundColor Cyan
}

function Pass([string]$Message) {
    Write-Host "PASS  $Message" -ForegroundColor Green
}

function Fail([string]$Message) {
    Write-Host "FAIL  $Message" -ForegroundColor Red
    $script:failures++
}

function Invoke-Checked([string]$Label, [scriptblock]$Action) {
    try {
        & $Action
        if ($LASTEXITCODE -ne 0) { Fail "$Label (exit code $LASTEXITCODE)" }
        else { Pass $Label }
    }
    catch {
        Fail "$Label ($_)"
    }
}

Step "Host"
Write-Host ((Get-CimInstance Win32_OperatingSystem).Caption)
Write-Host ("Build : " + [System.Environment]::OSVersion.Version)
Write-Host ("Arch  : " + $env:PROCESSOR_ARCHITECTURE)
if ([System.Environment]::OSVersion.Version.Major -lt 10) {
    Fail "Windows 10 or newer is required"
} else {
    Pass "Windows version supported (Windows 11 is build 22000+)"
}

Step "Interpreter"
if (-not $Python) {
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) { $Python = "py" }
    else {
        $candidate = Get-Command python -ErrorAction SilentlyContinue
        if ($candidate) { $Python = $candidate.Source } else { Fail "No Python found. Install Python 3.11 x64 from python.org."; exit 1 }
    }
}
$versionArgs = @("--version")
if ($Python -eq "py") { $versionArgs = @("-3.11", "--version") }
$version = & $Python @versionArgs 2>&1
Write-Host $version
if ($version -match "3\.(1[1-9]|[2-9][0-9])") { Pass "Python version supported" } else { Fail "Python 3.11+ required (found $version)" }

Step "Virtual environment"
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    $venvArgs = @("-m", "venv", ".venv")
    if ($Python -eq "py") { & py -3.11 @venvArgs } else { & $Python @venvArgs }
    if ($LASTEXITCODE -ne 0) { Fail "venv creation failed"; exit 1 }
}
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
Pass "venv ready ($venvPython)"

Step "Dependencies"
Invoke-Checked "pip install -r requirements.txt" { & $venvPython -m pip install --quiet --upgrade pip; & $venvPython -m pip install --quiet -r requirements.txt }
Invoke-Checked "pip install -r requirements-dev.txt" { & $venvPython -m pip install --quiet -r requirements-dev.txt }

Step "Portability"
& $venvPython scripts\check_portability.py
if ($LASTEXITCODE -ne 0) { Fail "portability check reported failures" } else { Pass "portability check" }

if (-not $SkipTests) {
    Step "Tests"
    & $venvPython -m pytest -q
    if ($LASTEXITCODE -ne 0) { Fail "pytest" } else { Pass "pytest" }
}

Step "GUI smoke test"
$smokeHome = Join-Path $env:TEMP ("myai-smoke-" + [guid]::NewGuid().ToString("N"))
$env:MYAI_STUDIO_HOME = $smokeHome
$proc = Start-Process -FilePath $venvPython -ArgumentList @("-m", "myai", "--smoke", "--allow-multi") -PassThru -NoNewWindow
if (-not $proc.WaitForExit(90000)) {
    $proc.Kill()
    Fail "the window did not start and exit within 90 s"
}
elseif ($proc.ExitCode -ne 0) {
    Fail "GUI smoke test exited with code $($proc.ExitCode); see $smokeHome\logs"
}
else {
    $log = Join-Path $smokeHome "logs\myai_studio.jsonl"
    if (Test-Path $log) {
        $booted = Select-String -Path $log -Pattern "app_booted" -Quiet
        if ($booted) { Pass "GUI started, logged app_booted, and exited cleanly" }
        else { Fail "GUI exited but never logged app_booted" }
    }
    else {
        Fail "GUI exited without writing a log file"
    }
}

Step "Summary"
if ($failures -eq 0) {
    Write-Host "ALL CHECKS PASSED on this Windows machine." -ForegroundColor Green
    exit 0
}
Write-Host "$failures check(s) failed." -ForegroundColor Red
exit 1
