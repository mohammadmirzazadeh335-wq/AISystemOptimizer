<#
.SYNOPSIS
    Launcher for MyAI Studio Ultimate on Windows 11.

.DESCRIPTION
    Prepares the virtual environment on first run, then starts the application.
    Pass any application switch through, e.g.:

        .\run_windows.ps1 -Args '--lang en','--theme dawn'

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File run_windows.ps1
#>
[CmdletBinding()]
param(
    [string[]]$Args = @()
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Fail([string]$message) {
    Write-Host "[ERROR] $message" -ForegroundColor Red
    Read-Host "Press Enter to close"
    exit 1
}

$python = $null
foreach ($candidate in @("py", "python")) {
    $command = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($command) { $python = $command.Source; break }
}
if (-not $python) {
    Fail "Python was not found on PATH. Install Python 3.10-3.13 from python.org and tick 'Add python.exe to PATH'."
}

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "[1/3] Creating virtual environment..." -ForegroundColor Cyan
    & $python -m venv .venv
    if ($LASTEXITCODE -ne 0) { Fail "Could not create the virtual environment." }

    Write-Host "[2/3] Installing dependencies..." -ForegroundColor Cyan
    & $venvPython -m pip install --upgrade pip | Out-Null
    & $venvPython -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { Fail "Dependency installation failed. Check your internet connection." }
} else {
    Write-Host "[1/3] Virtual environment found." -ForegroundColor DarkGray
}

Write-Host "[3/3] Starting MyAI Studio Ultimate..." -ForegroundColor Green
& $venvPython -m myai @Args
if ($LASTEXITCODE -ne 0) {
    Fail "The application exited with code $LASTEXITCODE. See %APPDATA%\MyAIStudio\logs\myai_studio.jsonl"
}
