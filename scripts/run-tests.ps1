<#
.SYNOPSIS
    Runs the unit tests with a readable report.
#>
[CmdletBinding()]
param(
    [string] $Filter = ''
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$project = Join-Path $root 'tests\AISystemOptimizer.Tests\AISystemOptimizer.Tests.csproj'

$testArgs = @('test', $project, '-v', 'normal', '--nologo')
if ($Filter) { $testArgs += @('--filter', $Filter) }

dotnet @testArgs
exit $LASTEXITCODE
