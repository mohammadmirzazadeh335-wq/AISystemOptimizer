<#
.SYNOPSIS
    Produces the portable single-file build (AIOptimizer.exe).

.DESCRIPTION
    Three flavours are supported:

      framework-dependent   ~5 MB, requires the .NET 8 Desktop Runtime on the target machine
      self-contained       ~80 MB, runs on any Windows 10 1809+ / Windows 11 x64 machine, no install

    The result is written to dist\ and zipped.

.PARAMETER Flavor
    'selfcontained' (default) or 'framework'.

.PARAMETER OutputName
    Base name of the produced executable. Defaults to AIOptimizer.

.EXAMPLE
    .\publish-portable.ps1
    .\publish-portable.ps1 -Flavor framework
#>
[CmdletBinding()]
param(
    [ValidateSet('selfcontained', 'framework')]
    [string] $Flavor = 'selfcontained',

    [string] $OutputName = 'AIOptimizer',

    [ValidateSet('win-x64', 'win-arm64')]
    [string] $Runtime = 'win-x64'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$project = Join-Path $root 'src\AISystemOptimizer.App\AISystemOptimizer.App.csproj'
$dist = Join-Path $root 'dist'

if (Test-Path $dist) { Remove-Item $dist -Recurse -Force }
New-Item -ItemType Directory -Path $dist | Out-Null

$selfContained = $Flavor -eq 'selfcontained'

Write-Host "== Publishing portable build ($Flavor, $Runtime) ==" -ForegroundColor Cyan

$publishArgs = @(
    'publish', $project,
    '-c', 'Release',
    '-r', $Runtime,
    '--self-contained', $selfContained.ToString().ToLowerInvariant(),
    '-p:PublishSingleFile=true',
    '-p:IncludeNativeLibrariesForSelfExtract=true',
    '-p:DebugType=None',
    '-p:DebugSymbols=false',
    "-p:PortableName=$OutputName",
    '-o', $dist
)

dotnet @publishArgs
if ($LASTEXITCODE -ne 0) { throw 'Publish failed.' }

$exe = Join-Path $dist "$OutputName.exe"
if (-not (Test-Path $exe)) { throw "Expected $exe was not produced." }

$zip = Join-Path $root "dist\AISystemOptimizer-portable-$Flavor.zip"
Compress-Archive -Path (Join-Path $dist '*') -DestinationPath $zip -Force

$size = [math]::Round((Get-Item $exe).Length / 1MB, 1)

Write-Host "`nPortable build ready." -ForegroundColor Green
Write-Host "Executable : $exe  ($size MB)"
Write-Host "Archive    : $zip"
Write-Host "`nPortable notes:" -ForegroundColor Cyan
Write-Host "  * Settings, logs and backups are written to %LOCALAPPDATA%\AISystemOptimizer."
Write-Host "  * To keep everything inside a folder instead, launch with:"
Write-Host "      `$env:AISYSTEMOPTIMIZER_PORTABLE=1`; .\$OutputName.exe"
