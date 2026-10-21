<#
.SYNOPSIS
    Build the Windows executable and (optionally) the installer for MyAI Studio Ultimate.

.DESCRIPTION
    Runs the test suite, packages the app with PyInstaller (onedir), verifies the
    packaged executable starts in smoke mode, and optionally compiles the Inno Setup
    installer. Fails loudly; it never reports success on a failed step.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
    powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1 -SkipTests -Installer
#>
[CmdletBinding()]
param(
    [string]$Version = "",
    [switch]$SkipTests,
    [switch]$Installer,
    [switch]$OneFile
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Step([string]$text) { Write-Host "`n=== $text ===" -ForegroundColor Cyan }
function Fail([string]$text) { Write-Host "FAILED: $text" -ForegroundColor Red; exit 1 }

if (-not $Version) {
    $Version = (python -c "from myai.version import VERSION; print(VERSION)").Trim()
    if ($LASTEXITCODE -ne 0) { Fail "could not read version from myai/version.py" }
}
Step "Building MyAI Studio Ultimate $Version"

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Step "Creating virtual environment"
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { Fail "venv creation failed" }
}
$python = ".venv\Scripts\python.exe"

Step "Installing build requirements"
& $python -m pip install --upgrade pip
& $python -m pip install -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { Fail "dependency installation failed" }

if (-not $SkipTests) {
    Step "Running tests"
    & $python -m pytest -q
    if ($LASTEXITCODE -ne 0) { Fail "tests failed - refusing to package" }
}

Step "Building executable with PyInstaller"
$mode = if ($OneFile) { "--onefile" } else { "--onedir" }
& $python -m PyInstaller `
    --noconfirm --clean $mode --windowed `
    --name "MyAIStudio" `
    --icon "assets\brand\myai.ico" `
    --add-data "myai\i18n\locales;myai\i18n\locales" `
    --add-data "assets;assets" `
    --collect-submodules "sqlalchemy.dialects.sqlite" `
    --hidden-import "cryptography.fernet" `
    packaging\launcher.py
if ($LASTEXITCODE -ne 0) { Fail "PyInstaller failed" }

$exe = if ($OneFile) { "dist\MyAIStudio.exe" } else { "dist\MyAIStudio\MyAIStudio.exe" }
if (-not (Test-Path $exe)) { Fail "expected executable not found at $exe" }

Step "Smoke-testing the packaged executable"
$tmpHome = Join-Path $env:TEMP ("myai-smoke-" + [guid]::NewGuid().ToString("N"))
$env:MYAI_STUDIO_HOME = $tmpHome
$proc = Start-Process -FilePath $exe -ArgumentList "--smoke","--allow-multi" -PassThru
if (-not $proc.WaitForExit(45000)) {
    $proc.Kill()
    Fail "packaged executable did not exit within 45s"
}
if ($proc.ExitCode -ne 0) { Fail "packaged executable exited with code $($proc.ExitCode)" }
Write-Host "Smoke test passed (exit code 0)" -ForegroundColor Green

if ($Installer) {
    Step "Compiling Inno Setup installer"
    $iscc = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $iscc) { Fail "Inno Setup 6 not found - install it or drop -Installer" }
    & $iscc "/DMyAppVersion=$Version" "packaging\myai_studio.iss"
    if ($LASTEXITCODE -ne 0) { Fail "Inno Setup compilation failed" }
    $installer = Get-ChildItem "dist\installer\*.exe" | Sort-Object LastWriteTime | Select-Object -Last 1
    if (-not $installer) { Fail "installer output not found" }
    Write-Host "Installer: $($installer.FullName)" -ForegroundColor Green
}

Step "Done"
Write-Host "Executable : $exe"
Write-Host "Version    : $Version"
