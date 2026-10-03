[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$GamesRoot,
    [switch]$ForceRetry
)

$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $GamesRoot -PathType Container)) {
    throw "Games directory does not exist: $GamesRoot"
}
$launcher = Get-Command py -ErrorAction Stop
$pythonOutput = & $launcher.Source -3 -c 'import sys; print(sys.executable)'
if ($LASTEXITCODE -ne 0 -or -not $pythonOutput) {
    throw 'Could not find a usable Python 3 installation.'
}
$python = ($pythonOutput | Select-Object -First 1).Trim()
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'Could not find a usable Python 3 installation.'
}
$script = Join-Path $PSScriptRoot 'auto_folder_icons.py'
$arguments = @($script, '--root', (Resolve-Path -LiteralPath $GamesRoot).Path, '--scan')
if ($ForceRetry) { $arguments += '--force-retry' }
& $python @arguments
exit $LASTEXITCODE
