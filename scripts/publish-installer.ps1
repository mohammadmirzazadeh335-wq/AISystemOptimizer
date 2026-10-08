<#
.SYNOPSIS
    Builds the installer (requires Inno Setup 6).

.DESCRIPTION
    Publishes the self-contained build and compiles installer\AISystemOptimizer.iss
    into dist\AISystemOptimizer-Setup.exe.

    Inno Setup is a free download: https://jrsoftware.org/isdl.php
#>
[CmdletBinding()]
param(
    [string] $Version = '1.0.0',
    [string] $InnoCompiler = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

if (-not (Test-Path $InnoCompiler)) {
    throw "Inno Setup compiler not found at '$InnoCompiler'. Install it or pass -InnoCompiler <path>."
}

# 1. publish the payload
& (Join-Path $PSScriptRoot 'publish-portable.ps1') -Flavor selfcontained -OutputName AIOptimizer

# 2. compile the installer
$iss = Join-Path $root 'installer\AISystemOptimizer.iss'
Write-Host "`nCompiling installer..." -ForegroundColor Cyan
& $InnoCompiler "/DMyAppVersion=$Version" $iss
if ($LASTEXITCODE -ne 0) { throw 'Inno Setup compilation failed.' }

Write-Host "`nInstaller ready: $root\dist\AISystemOptimizer-Setup.exe" -ForegroundColor Green
