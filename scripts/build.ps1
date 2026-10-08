<#
.SYNOPSIS
    Builds AI System Optimizer.

.DESCRIPTION
    Restores, builds and (optionally) tests the solution.
    Run from a Developer PowerShell or any PowerShell 5.1+/7+ session.

.PARAMETER Configuration
    Debug (default) or Release.

.PARAMETER SkipTests
    Skip the unit test run.

.EXAMPLE
    .\build.ps1 -Configuration Release
#>
[CmdletBinding()]
param(
    [ValidateSet('Debug', 'Release')]
    [string] $Configuration = 'Debug',

    [switch] $SkipTests
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$solution = Join-Path $root 'AISystemOptimizer.sln'

if (-not (Test-Path $solution)) {
    throw "Solution not found at $solution"
}

Write-Host "== AI System Optimizer build ==" -ForegroundColor Cyan
Write-Host "Solution : $solution"
Write-Host "Config   : $Configuration"

Write-Host "`n[1/3] Restoring packages..." -ForegroundColor Cyan
dotnet restore $solution
if ($LASTEXITCODE -ne 0) { throw 'Restore failed.' }

Write-Host "`n[2/3] Building..." -ForegroundColor Cyan
dotnet build $solution -c $Configuration --no-restore
if ($LASTEXITCODE -ne 0) { throw 'Build failed.' }

if (-not $SkipTests) {
    Write-Host "`n[3/3] Running tests..." -ForegroundColor Cyan
    dotnet test $solution -c $Configuration --no-build --nologo
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed.' }
}
else {
    Write-Host "`n[3/3] Tests skipped." -ForegroundColor Yellow
}

$output = Join-Path $root "src\AISystemOptimizer.App\bin\$Configuration\net8.0-windows\win-x64\AISystemOptimizer.exe"
Write-Host "`nBuild complete." -ForegroundColor Green
Write-Host "Executable: $output"
